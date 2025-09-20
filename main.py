from fastapi import FastAPI, HTTPException, File, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess
import os
import traceback
import shutil
import uuid

app = FastAPI()

# --- Manim Rendering Section ---
class RenderRequest(BaseModel):
    scene: str
    script: str

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Render with Manim and Video Tools!"}

@app.post("/render")
def render_scene(request: RenderRequest):
    try:
        scene = request.scene
        script = request.script
        
        output_dir = "/app/media"
        os.makedirs(output_dir, exist_ok=True)

        script_file_path = "/app/scene.py"
        with open(script_file_path, "w") as f:
            f.write(script)

        print(f"Running manim command for scene: {scene}...")
        cmd = [
            "manim", "-qm", script_file_path, scene, # Using -qm for 16:9 aspect ratio
            "--media_dir", output_dir
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            print(f"Error running manim: {result.stderr}")
            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=result.stderr
            )

        video_path = os.path.join(output_dir, "videos", "scene", "720p30", f"{scene}.mp4")
        
        if os.path.exists(video_path):
            print("Video file found, returning file...")
            return FileResponse(video_path, media_type="video/mp4", filename=f"{scene}.mp4")
        else:
            print(f"Error: Video not found at {video_path}")
            raise HTTPException(status_code=404, detail="Rendered video not found, but Manim process succeeded.")

    except subprocess.CalledProcessError as e:
        error_details = e.stderr or "No error output captured."
        raise HTTPException(status_code=500, detail=f"Error during Manim execution: {error_details}")
    
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="An unexpected server error occurred.")

# --- NEW: Image + Audio Stitching Section ---

def cleanup_files(paths: list):
    """A background task to delete files after they have been sent."""
    for path in paths:
        if os.path.exists(path):
            os.remove(path)
            print(f"Cleaned up temporary file: {path}")

@app.post("/stitch")
async def stitch_image_and_audio(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    audio: UploadFile = File(...)
):
    """
    This endpoint receives an image and an audio file, and stitches them
    into a video using ffmpeg. The video duration will match the audio duration.
    """
    # Create a unique filename to avoid conflicts during simultaneous requests
    job_id = str(uuid.uuid4())
    temp_dir = "/app/media/temp"
    os.makedirs(temp_dir, exist_ok=True)
    
    # Define file paths
    image_ext = os.path.splitext(image.filename)[1]
    audio_ext = os.path.splitext(audio.filename)[1]
    
    temp_image_path = os.path.join(temp_dir, f"{job_id}{image_ext}")
    temp_audio_path = os.path.join(temp_dir, f"{job_id}{audio_ext}")
    output_video_path = os.path.join(temp_dir, f"{job_id}.mp4")

    try:
        # Save the uploaded files to the server's disk
        with open(temp_image_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        with open(temp_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
            
        print(f"Saved temporary files: {temp_image_path}, {temp_audio_path}")

        # Construct the ffmpeg command to combine the image and audio
        cmd = [
            "ffmpeg",
            "-loop", "1",                      # Loop the single input image
            "-i", temp_image_path,             # Input image file
            "-i", temp_audio_path,             # Input audio file
            "-c:v", "libx264",                 # Video codec
            "-tune", "stillimage",             # Optimize for static images
            "-c:a", "aac",                     # Audio codec
            "-b:a", "192k",                    # Audio bitrate
            "-pix_fmt", "yuv420p",             # Pixel format for compatibility
            "-shortest",                       # Make video duration match the audio's duration
            output_video_path
        ]

        print("Running ffmpeg stitch command...")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            print(f"Error during ffmpeg stitching: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"Failed to stitch video: {result.stderr}")

        if not os.path.exists(output_video_path):
            raise HTTPException(status_code=500, detail="Stitching process finished, but the output video was not found.")

        # Add all temporary files to be cleaned up after the response is sent
        background_tasks.add_task(cleanup_files, [temp_image_path, temp_audio_path, output_video_path])
        
        print(f"Stitching successful. Returning video: {output_video_path}")
        return FileResponse(output_video_path, media_type="video/mp4", filename="stitched_video.mp4")

    except Exception as e:
        # Clean up files immediately if a critical error occurs before the response
        cleanup_files([temp_image_path, temp_audio_path, output_video_path])
        print(f"An unexpected error occurred during stitching: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred: {str(e)}")
