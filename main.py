from fastapi import FastAPI, HTTPException, File, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import subprocess
import os
import traceback
import shutil
import uuid
from PIL import Image
import io

# This defines the FastAPI application instance. It must be here, before any routes.
app = FastAPI()

# --- Manim Rendering Section (Unchanged) ---
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
        cmd = ["manim", "-qm", script_file_path, scene, "--media_dir", output_dir]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=result.stderr
            )
        video_path = os.path.join(output_dir, "videos", "scene", "720p30", f"{scene}.mp4")
        if os.path.exists(video_path):
            return FileResponse(video_path, media_type="video/mp4", filename=f"{scene}.mp4")
        else:
            raise HTTPException(status_code=404, detail="Rendered video not found.")
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Error during Manim execution: {e.stderr}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="An unexpected server error occurred.")

# --- Image Conversion Endpoint (Unchanged) ---
@app.post("/convert-to-jpg")
async def convert_image_to_jpg(image: UploadFile = File(...)):
    try:
        image_bytes = await image.read()
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        jpg_buffer = io.BytesIO()
        img.save(jpg_buffer, format='JPEG', quality=85)
        jpg_buffer.seek(0)
        return StreamingResponse(jpg_buffer, media_type="image/jpeg", headers={"Content-Disposition": "attachment; filename=converted_image.jpg"})
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to convert image: {str(e)}")

# --- Audio Compression Endpoint (Unchanged) ---
@app.post("/compress-audio")
async def compress_audio(background_tasks: BackgroundTasks, audio: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    temp_dir = "/app/media/temp"
    os.makedirs(temp_dir, exist_ok=True)
    audio_ext = os.path.splitext(audio.filename)[1] if audio.filename else '.mp3'
    temp_input_path = os.path.join(temp_dir, f"{job_id}_input{audio_ext}")
    temp_output_path = os.path.join(temp_dir, f"{job_id}_output.mp3")
    try:
        with open(temp_input_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
        cmd = ["ffmpeg", "-i", temp_input_path, "-b:a", "96k", temp_output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Failed to compress audio: {result.stderr}")
        if not os.path.exists(temp_output_path):
            raise HTTPException(status_code=500, detail="Compression finished, but output file not found.")
        background_tasks.add_task(cleanup_files, [temp_input_path, temp_output_path])
        return FileResponse(temp_output_path, media_type="audio/mpeg", filename="compressed_audio.mp3")
    except Exception as e:
        cleanup_files([temp_input_path, temp_output_path])
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred during audio compression: {str(e)}")


# --- Image + Audio Stitching Section (NEW ASYNC VERSION) ---

# 1. In-memory storage for our tasks.
# For production, consider using Redis or a database.
tasks = {}

# 2. The new background function that does the actual work.
def process_stitching_task(task_id: str, temp_image_path: str, temp_audio_path: str, output_video_path: str, video_bitrate: str, audio_bitrate: str):
    """
    This function runs in the background. It performs the ffmpeg command
    and updates the task status in our `tasks` dictionary.
    """
    try:
        # Update status to 'processing'
        tasks[task_id]['status'] = 'processing'
        
        # The same ffmpeg command you had before
        cmd = [
            "ffmpeg", "-loop", "1", "-i", temp_image_path, "-i", temp_audio_path,
            "-c:v", "libx264", "-b:v", video_bitrate, "-tune", "stillimage",
            "-c:a", "aac", "-b:a", audio_bitrate, "-pix_fmt", "yuv420p",
            "-shortest", output_video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            # If ffmpeg fails, record the error
            raise Exception(result.stderr)

        # If successful, mark as complete and store the path
        tasks[task_id]['status'] = 'complete'
        tasks[task_id]['output_path'] = output_video_path
        print(f"Task {task_id} completed successfully.")

    except Exception as e:
        # If any error occurs, mark as failed and store the error message
        print(f"Task {task_id} failed: {e}")
        tasks[task_id]['status'] = 'failed'
        tasks[task_id]['error'] = str(e)
    finally:
        # Clean up the input files, but leave the output file for download
        cleanup_files([temp_image_path, temp_audio_path])

# 3. The POST endpoint to SUBMIT a new stitching job.
@app.post("/stitch/submit")
async def submit_stitching_job(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    quality: str = 'low'
):
    # Set bitrate based on quality parameter
    bitrates = {
        'high': ("2000k", "192k"),
        'medium': ("1000k", "128k"),
        'low': ("500k", "96k")
    }
    video_bitrate, audio_bitrate = bitrates.get(quality, bitrates['low'])

    # Prepare file paths
    task_id = str(uuid.uuid4())
    temp_dir = "/app/media/temp"
    os.makedirs(temp_dir, exist_ok=True)
    image_ext = os.path.splitext(image.filename)[1] if image.filename else '.jpg'
    audio_ext = os.path.splitext(audio.filename)[1] if audio.filename else '.mp3'
    temp_image_path = os.path.join(temp_dir, f"{task_id}{image_ext}")
    temp_audio_path = os.path.join(temp_dir, f"{task_id}{audio_ext}")
    output_video_path = os.path.join(temp_dir, f"{task_id}.mp4")

    # Save uploaded files to disk first
    try:
        with open(temp_image_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        with open(temp_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded files: {str(e)}")

    # Create the task entry
    tasks[task_id] = {'status': 'pending'}

    # Add the processing function to run in the background
    background_tasks.add_task(
        process_stitching_task, task_id, temp_image_path, temp_audio_path,
        output_video_path, video_bitrate, audio_bitrate
    )

    # Immediately return the task_id
    return {"message": "Stitching job accepted.", "task_id": task_id}

# 4. The GET endpoint to check STATUS and get the final video.
@app.get("/stitch/status/{task_id}")
def get_stitching_status(task_id: str, background_tasks: BackgroundTasks):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task ID not found.")

    if task['status'] == 'complete':
        output_path = task.get('output_path')
        if output_path and os.path.exists(output_path):
            # When the file is requested, schedule it for cleanup after sending
            background_tasks.add_task(cleanup_files, [output_path])
            return FileResponse(output_path, media_type="video/mp4", filename="stitched_video.mp4")
        else:
            return {"status": "failed", "error": "Output file not found."}
    
    elif task['status'] == 'failed':
        return {"status": "failed", "error": task.get('error', 'An unknown error occurred.')}
    
    # For 'pending' or 'processing' status
    return {"status": task['status']}

def cleanup_files(paths: list):
    for path in paths:
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"Cleaned up file: {path}")
            except OSError as e:
                print(f"Error cleaning up file {path}: {e}")