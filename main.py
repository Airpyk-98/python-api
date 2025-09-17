from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess
import os

app = FastAPI()

class Numbers(BaseModel):
    a: int
    b: int

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Render with Manim!"}

@app.post("/add")
def add_numbers(numbers: Numbers):
    return {"result": numbers.a + numbers.b}

# ✅ New endpoint for Manim rendering
@app.get("/render")
def render_scene():
    output_dir = "/app/media/videos"
    os.makedirs(output_dir, exist_ok=True)

    # Run manim on example.py with the SquareToCircle scene
    cmd = [
        "manim", "-ql", "example.py", "SquareToCircle",
        "--media_dir", output_dir
    ]
    subprocess.run(cmd, check=True)

    # Path to the generated video (default by manim)
    video_path = os.path.join(output_dir, "example/480p15/SquareToCircle.mp4")

    # Debugging: log the full path where the video should be stored
    print(f"Video should be stored at: {video_path}")
    
    # Check the files in the directory to confirm the video is saved
    files_in_dir = os.listdir(os.path.dirname(video_path))
    print(f"Files in the directory: {files_in_dir}")

    # Check if the video exists
    if os.path.exists(video_path):
        return FileResponse(video_path, media_type="video/mp4", filename="SquareToCircle.mp4")
    else:
        return {"error": f"Video not found after rendering. Path: {video_path}. Files: {files_in_dir}"}
