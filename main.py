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

# --- Image + Audio Stitching Section (UPDATED) ---
def cleanup_files(paths: list):
    for path in paths:
        if os.path.exists(path):
            os.remove(path)

@app.post("/stitch")
async def stitch_image_and_audio(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    quality: str = 'low' # UPDATED: Added quality parameter, defaults to 'low'
):
    # Set bitrate based on quality parameter
    if quality == 'high':
        video_bitrate = "2000k"
        audio_bitrate = "192k"
    elif quality == 'medium':
        video_bitrate = "1000k"
        audio_bitrate = "128k"
    else: # Default to low quality
        video_bitrate = "500k"
        audio_bitrate = "96k"

    job_id = str(uuid.uuid4())
    temp_dir = "/app/media/temp"
    os.makedirs(temp_dir, exist_ok=True)
    image_ext = os.path.splitext(image.filename)[1] if image.filename else '.jpg'
    audio_ext = os.path.splitext(audio.filename)[1] if audio.filename else '.mp3'
    temp_image_path = os.path.join(temp_dir, f"{job_id}{image_ext}")
    temp_audio_path = os.path.join(temp_dir, f"{job_id}{audio_ext}")
    output_video_path = os.path.join(temp_dir, f"{job_id}.mp4")
    try:
        with open(temp_image_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        with open(temp_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
        
        # UPDATED: The ffmpeg command now uses the bitrates defined above
        cmd = ["ffmpeg", "-loop", "1", "-i", temp_image_path, "-i", temp_audio_path, "-c:v", "libx24", "-b:v", video_bitrate, "-tune", "stillimage", "-c:a", "aac", "-b:a", audio_bitrate, "-pix_fmt", "yuv420p", "-shortest", output_video_path]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Failed to stitch video: {result.stderr}")
        if not os.path.exists(output_video_path):
            raise HTTPException(status_code=500, detail="Stitching process finished, but the output video was not found.")
        background_tasks.add_task(cleanup_files, [temp_image_path, temp_audio_path, output_video_path])
        return FileResponse(output_video_path, media_type="video/mp4", filename="stitched_video.mp4")
    except Exception as e:
        cleanup_files([temp_image_path, temp_audio_path, output_video_path])
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred: {str(e)}")
