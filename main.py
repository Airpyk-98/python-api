from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess
import os
import traceback

app = FastAPI()

# Define the input data structure for the POST request
class RenderRequest(BaseModel):
    scene: str
    script: str

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Render with Manim!"}

@app.post("/render")
def render_scene(request: RenderRequest):
    try:
        # Extract scene and script from the request body
        scene = request.scene
        script = request.script
        
        # Define the output directory
        output_dir = "/app/media/videos"
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "example"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "example", "480p15"), exist_ok=True)

        # Save the script to a Python file
        script_file_path = "/app/scene.py"
        with open(script_file_path, "w") as f:
            f.write(script)

        # Run the Manim command with the provided scene and script
        print(f"Running manim command for scene: {scene}...")
        cmd = [
            "manim", "-ql", script_file_path, scene,
            "--media_dir", output_dir
        ]
        subprocess.run(cmd, check=True)

        # Correct video path based on the Manim output
        video_path = os.path.join(output_dir, f"videos/example/480p15/{scene}.mp4")

        # Log the path and check if the file exists
        print(f"Video path: {video_path}")
        print(f"Files in directory: {os.listdir(os.path.dirname(video_path))}")

        # Check if the video exists
        if os.path.exists(video_path):
            print("Video file found, returning file...")
            return FileResponse(video_path, media_type="video/mp4", filename=f"{scene}.mp4")
        else:
            print(f"Error: Video not found at {video_path}")
            raise HTTPException(status_code=404, detail=f"Video not found at {video_path}")

    except subprocess.CalledProcessError as e:
        print(f"Error running manim: {e}")
        traceback.print_exc()  # Print the full traceback of the error
        raise HTTPException(status_code=500, detail="Error occurred while rendering video.")
    
    except FileNotFoundError as e:
        print(f"FileNotFoundError: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=404, detail=f"File not found: {str(e)}")
    
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
