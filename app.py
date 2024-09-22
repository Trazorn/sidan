from flask import Flask, render_template, request, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, TextClip, vfx
import os
from PIL import Image, UnidentifiedImageError
from moviepy.config import change_settings
from uuid import uuid4
from datetime import datetime
import traceback

# Set the path to ImageMagick
change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"})

app = Flask(__name__)

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///videos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Path to the default video file
DEFAULT_VIDEO_PATH = r"C:\Users\limpa\Downloads\Videon.mp4"

# Ensure the uploads and output folders exist
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'output'
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# Database Models
class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), nullable=False)
    likes = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)  # Track when the video was uploaded


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    ip_address = db.Column(db.String(100), nullable=False)

def generate_progress_callback(queue):
    """
    A callback function to update the progress queue for SSE events.
    """
    def progress_callback(complete, duration):
        progress = int(complete / duration * 100)
        queue.put(progress)
        if progress == 100:  # Ensuring the last 100% progress is sent
            queue.put(100)
    return progress_callback

# Function to validate image content
def is_valid_image(image_file):
    try:
        img = Image.open(image_file)
        img.verify()  # Verify if this is an image
        return True
    except (UnidentifiedImageError, OSError):
        return False

@app.route('/')
def index():
    # Retrieve all videos from the database
    videos = Video.query.all()
    return render_template('index.html', videos=videos)

@app.route('/upload', methods=['POST'])
def upload_background():
    try:
        # Get the uploaded image file and texts
        image_file = request.files['image']
        text1 = request.form['text1']
        text2 = request.form['text2']
        text3 = request.form['text3']
        text4 = request.form['text4']

        # Validate image content
        if not is_valid_image(image_file):
            return jsonify({"error": "Invalid image file. Please upload a valid JPG or PNG image."}), 400

        # Save the image to the upload folder
        image_path = os.path.join(UPLOAD_FOLDER, image_file.filename)
        image_file.seek(0)  # Reset file pointer after validation
        image_file.save(image_path)

        # Load the default green-screen video
        video_clip = VideoFileClip(DEFAULT_VIDEO_PATH)

        # Apply chroma key effect to remove green background
        transparent_video = video_clip.fx(vfx.mask_color, color=[0, 255, 0], thr=100, s=5)

        # Load the uploaded background image
        background_image = ImageClip(image_path).set_duration(transparent_video.duration).resize(transparent_video.size)

        # Create text clips with specific positions and timings
        text_1 = TextClip(text1, fontsize=70, color='black', font='Arial-Bold').set_position(('left', 'top')).set_duration(3).set_start(0)
        text_2 = TextClip(text2, fontsize=70, color='black', font='Arial-Bold').set_position(('right', 'top')).set_duration(1).set_start(3)
        text_3 = TextClip(text3, fontsize=70, color='black', font='Arial-Bold').set_position(('left', 'top')).set_duration(4.5).set_start(4)
        text_4 = TextClip(text4, fontsize=70, color='black', font='Arial-Bold').set_position(('right', 'top')).set_duration(transparent_video.duration - 8.5).set_start(8.5)

        # Composite the video, background, and text clips
        composite = CompositeVideoClip([background_image, transparent_video, text_1, text_2, text_3, text_4])

        # Generate a unique filename for the video
        unique_filename = f"processed_video_{str(uuid4())}.mp4"
        output_path = os.path.join(OUTPUT_FOLDER, unique_filename)
        composite.write_videofile(output_path, codec='libx264', fps=24)

        # Save the video info to the database
        new_video = Video(filename=unique_filename)
        db.session.add(new_video)
        db.session.commit()

        # Return the URL of the newly created video
        return jsonify({"video_url": f"/video/{new_video.id}"}), 200

    except Exception as e:
        # Capture error details and return a friendly message
        error_message = f"An error occurred during video processing: {str(e)}"
        traceback.print_exc()  # Log the traceback for debugging
        return jsonify({"error": error_message}), 500

@app.route('/video/<int:video_id>', methods=['GET'])
def get_video(video_id):
    video = Video.query.get(video_id)
    if video:
        video_path = os.path.join(OUTPUT_FOLDER, video.filename)
        if os.path.exists(video_path):
            return send_file(video_path, mimetype='video/mp4')
        else:
            return jsonify({"error": "Video file not found."}), 404
    else:
        return jsonify({"error": "Video not found."}), 404

@app.route('/videos', methods=['GET'])
def get_videos():
    # Get query parameters for pagination (page and limit)
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 5))
    
    # Query the videos, order by timestamp (newest first), and paginate
    videos = Video.query.order_by(Video.timestamp.desc()).paginate(page=page, per_page=limit, error_out=False)
    
    videos_data = [{"id": video.id, "filename": video.filename, "likes": video.likes} for video in videos.items]
    
    return jsonify({
        "videos": videos_data,
        "total": videos.total,  # Total number of videos in the database
        "page": videos.page,  # Current page
        "pages": videos.pages  # Total number of pages
    })


@app.route('/like/<video_id>', methods=['POST'])
def like_video(video_id):
    video = Video.query.filter_by(id=video_id).first()

    if not video:
        return jsonify({"error": "Video not found."}), 404

    # Get the user's IP address
    user_ip = request.remote_addr

    # Check if the user has already liked this video
    if Like.query.filter_by(video_id=video_id, ip_address=user_ip).first():
        return jsonify({"message": "You have already liked this video."}), 400

    # Add the like
    new_like = Like(video_id=video_id, ip_address=user_ip)
    db.session.add(new_like)

    # Increment the like count
    video.likes += 1
    db.session.commit()

    return jsonify({"message": "Video liked!", "likes": video.likes}), 200


if __name__ == '__main__':
    # Ensure the database tables are created within an application context
    with app.app_context():
        db.create_all()
    app.run(debug=True)
