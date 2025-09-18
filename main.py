from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess
import os
import traceback

app = FastAPI()

class RenderRequest(BaseModel):
    scene: str
    script: str

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Render with Manim!"}

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
            "manim", "-ql", script_file_path, scene,
            "--media_dir", output_dir
        ]

        # Run the command and capture the output
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Check if the command failed (returncode is not 0)
        if result.returncode != 0:
            print(f"Error running manim: {result.stderr}")
            # If Manim fails, raise an error with its specific output
            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=result.stderr
            )

        video_path = os.path.join(output_dir, "videos", "scene", "480p15", f"{scene}.mp4")
        
        if os.path.exists(video_path):
            print("Video file found, returning file...")
            return FileResponse(video_path, media_type="video/mp4", filename=f"{scene}.mp4")
        else:
            print(f"Error: Video not found at {video_path}")
            raise HTTPException(status_code=404, detail="Rendered video not found, but Manim process succeeded.")

    except subprocess.CalledProcessError as e:
        # This is now the key: return the REAL error message from Manim
        error_details = e.stderr or "No error output captured."
        raise HTTPException(status_code=500, detail=f"Error during Manim execution: {error_details}")
    
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="An unexpected server error occurred.")