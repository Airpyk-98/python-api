@app.post("/stitch/submit")
async def submit_stitching_job(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    audios: List[UploadFile] = File(...),
    quality: str = 'low'
):
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
    
    # This is the corrected block. The `try` is correctly followed by `except`.
    try:
        # Save the single image file
        with open(temp_image_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)

        # Loop through and save all uploaded audio files
        audio_paths = []
        for i, audio_file in enumerate(audios):
            audio_ext = os.path.splitext(audio_file.filename)[1] if audio_file.filename else '.mp3'
            temp_audio_path = os.path.join(temp_dir, f"{task_id}_{i}{audio_ext}")
            with open(temp_audio_path, "wb") as buffer:
                shutil.copyfileobj(audio_file.file, buffer)
            audio_paths.append(temp_audio_path)

    except Exception as e:
        # This 'except' block was likely missing or misaligned in your file.
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded files: {str(e)}")

    tasks[task_id] = {'status': 'pending'}
    background_tasks.add_task(
        process_stitching_task, task_id, temp_image_path, audio_paths,
        output_video_path, video_bitrate, audio_bitrate
    )
    return {"message": "Stitching job accepted.", "task_id": task_id}