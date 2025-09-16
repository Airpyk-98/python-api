from fastapi import FastAPI
from pydantic import BaseModel
import subprocess
import os

app = FastAPI()

# Your original Numbers model
class Numbers(BaseModel):
    a: int
    b: int

# Existing root endpoint
@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Render!"}

# Existing add endpoint
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
        "manim", "-pql", "example.py", "SquareToCircle",
        "--media_dir", output_dir
    ]
    subprocess.run(cmd, check=True)

    return {"message": "Video rendered!", "path": output_dir}
