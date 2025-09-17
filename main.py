from fastapi import FastAPI, HTTPException
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

# ✅ New endpoint for Manim rendering with enhanced error handling and logging
@app.get("/render")
def render_scene():
    try:
        output_dir = "/app/media/videos"
        # Ensure all necessary directories exist
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "example"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "example", "480p15"), exist_ok=True)

        # Run manim on example.py with the SquareToCircle scene
        print(f"Running manim command...")
        cmd = [
            "manim", "-ql", "example.py", "SquareToCircle",
            "--media_dir", output_dir
        ]
        subprocess.run(cmd, check=True)

        # Path to the generated video (default by manim)
        video_path = os.path.join(output_dir, "example/480p15/SquareToCircle.mp4")
        
        # Log the path and check if the file exists
        print(f"Video path: {video_path}")
        print(f"Files in directory: {os.listdir(os.path.dirname(video_path))}")

        # Check if the video exists
        if os.path.exists(video_path):
            print("Video file found, returning file...")
            return FileResponse(video_path, media_type="video/mp4", filename="SquareToCircle.mp4")
        else:
            print(f"Error: Video not found at {video_path}")
            raise HTTPException(status_code=404, detail=f"Video not found at {video_path}")

    except subprocess.CalledProcessError as e:
        # If there was an error running manim
        print(f"Error running manim: {e}")
        raise HTTPException(status_code=500, detail="Error occurred while rendering video.")
    except Exception as e:
        # General error handler
        print(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
