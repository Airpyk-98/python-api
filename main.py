from fastapi import FastAPI, HTTPException, File, UploadFile, BackgroundTasks, Form
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import subprocess
import os
import traceback
import shutil
import uuid
from PIL import Image
import io
from typing import List, Optional
import requests
import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# This defines the FastAPI application instance. It must be at the top.
app = FastAPI()

# Create the scheduler instance that will run our cleanup job
scheduler = AsyncIOScheduler()

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

# --- Image Conversion Endpoint ---
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

# --- Audio Compression Endpoint ---
@app.post("/compress-audio")
async def compress_audio(audio: UploadFile = File(...)):
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
        # NOTE: Immediate cleanup is removed. The scheduled job will handle this file.
        return FileResponse(temp_output_path, media_type="audio/mpeg", filename="compressed_audio.mp3")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred during audio compression: {str(e)}")


# --- Image + Audio Stitching Section (with Scheduled Cleanup) ---
tasks = {}

def process_stitching_task(task_id: str, temp_image_path: str, audio_paths: List[str], output_video_path: str, video_bitrate: str, audio_bitrate: str):
    try:
        tasks[task_id]['status'] = 'processing'
        cmd = ["ffmpeg", "-loop", "1", "-i", temp_image_path]
        for audio_path in audio_paths:
            cmd.extend(["-i", audio_path])
        
        num_audios = len(audio_paths)
        audio_inputs = "".join([f"[{i+1}:a]" for i in range(num_audios)])
        filter_complex = f"{audio_inputs}concat=n={num_audios}:v=0:a=1[outa]"

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[outa]",
            "-c:v", "libx264", "-b:v", video_bitrate, "-tune", "stillimage",
            "-c:a", "aac", "-b:a", audio_bitrate, "-pix_fmt", "yuv420p",
            "-shortest", output_video_path
        ])
        
        print("Executing FFMPEG command:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            raise Exception(result.stderr)

        tasks[task_id]['status'] = 'complete'
        tasks[task_id]['output_path'] = output_video_path
        print(f"Task {task_id} completed successfully.")

    except Exception as e:
        print(f"Task {task_id} failed: {e}")
        tasks[task_id]['status'] = 'failed'
        tasks[task_id]['error'] = str(e)
    # NOTE: The 'finally' block that deleted input files is removed. The scheduled job will handle it.

@app.post("/stitch/submit")
async def submit_stitching_job(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    audios: Optional[List[UploadFile]] = File(None),
    audio_urls: Optional[List[str]] = Form(None),
    quality: str = 'low'
):
    if not audios and not audio_urls:
        raise HTTPException(status_code=400, detail="You must provide either audio files or audio URLs.")
    if audios and audio_urls:
        raise HTTPException(status_code=400, detail="Please provide either audio files or audio URLs, not both.")

    bitrates = {
        'high': ("2000k", "192k"), 'medium': ("1000k", "128k"), 'low': ("500k", "96k")
    }
    video_bitrate, audio_bitrate = bitrates.get(quality, bitrates['low'])
    task_id = str(uuid.uuid4())
    temp_dir = "/app/media/temp"
    os.makedirs(temp_dir, exist_ok=True)
    
    image_ext = os.path.splitext(image.filename)[1] if image.filename else '.jpg'
    temp_image_path = os.path.join(temp_dir, f"{task_id}{image_ext}")
    output_video_path = os.path.join(temp_dir, f"{task_id}.mp4")
    audio_paths = []
    
    try:
        with open(temp_image_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        
        if audios:
            for i, audio_file in enumerate(audios):
                audio_ext = os.path.splitext(audio_file.filename)[1] if audio_file.filename else '.mp3'
                temp_audio_path = os.path.join(temp_dir, f"{task_id}_{i}{audio_ext}")
                with open(temp_audio_path, "wb") as buffer:
                    shutil.copyfileobj(audio_file.file, buffer)
                audio_paths.append(temp_audio_path)
        elif audio_urls:
            for i, url in enumerate(audio_urls):
                try:
                    response = requests.get(url, stream=True)
                    response.raise_for_status()
                    temp_audio_path = os.path.join(temp_dir, f"{task_id}_{i}.mp3")
                    with open(temp_audio_path, "wb") as buffer:
                        for chunk in response.iter_content(chunk_size=8192):
                            buffer.write(chunk)
                    audio_paths.append(temp_audio_path)
                except requests.RequestException as e:
                    raise HTTPException(status_code=400, detail=f"Failed to download audio from URL: {url}. Error: {e}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded files: {str(e)}")
    
    tasks[task_id] = {'status': 'pending'}
    background_tasks.add_task(
        process_stitching_task, task_id, temp_image_path, audio_paths,
        output_video_path, video_bitrate, audio_bitrate
    )
    return {"message": "Stitching job accepted.", "task_id": task_id}

@app.get("/stitch/status/{task_id}")
def get_stitching_status(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    if task['status'] == 'complete':
        output_path = task.get('output_path')
        if output_path and os.path.exists(output_path):
            # NOTE: Immediate cleanup on download has been removed.
            return FileResponse(output_path, media_type="video/mp4", filename="stitched_video.mp4")
        else:
            return {"status": "complete", "detail": "Output file has been cleaned up by the scheduled job."}
    elif task['status'] == 'failed':
        return {"status": "failed", "error": task.get('error', 'An unknown error occurred.')}
    return {"status": task['status']}

# --- NEW SCHEDULED CLEANUP LOGIC ---
def cleanup_old_files():
    """Scans the temp directory and deletes files older than 24 hours."""
    temp_dir = "/app/media/temp"
    if not os.path.isdir(temp_dir):
        return
    
    twenty_four_hours_ago = time.time() - (24 * 60 * 60)
    
    print("Running scheduled cleanup of old files...")
    for filename in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                file_mod_time = os.path.getmtime(file_path)
                if file_mod_time < twenty_four_hours_ago:
                    os.remove(file_path)
                    print(f"Cleaned up old file: {filename}")
        except Exception as e:
            print(f"Error cleaning up file {file_path}: {e}")
    print("Scheduled cleanup finished.")

@app.on_event("startup")
async def startup_event():
    # Schedule the cleanup job to run every hour
    scheduler.add_job(cleanup_old_files, 'interval', hours=1)
    scheduler.start()
