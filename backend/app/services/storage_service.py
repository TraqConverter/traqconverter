import os
import uuid

BASE_UPLOAD_DIR = "uploads"


def save_file_locally(file, team_id: str):
    project_id = str(uuid.uuid4())

    directory = os.path.join(BASE_UPLOAD_DIR, team_id, project_id)
    os.makedirs(directory, exist_ok=True)

    file_path = os.path.join(directory, file.filename)

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return file_path, project_id


def save_certification_file(file, user_id: str):
    directory = os.path.join(BASE_UPLOAD_DIR, "certifications", user_id)
    os.makedirs(directory, exist_ok=True)

    file_path = os.path.join(directory, file.filename)

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return file_path