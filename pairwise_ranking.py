import os
import json
import itertools
import threading
import random
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ---------------------------
# Configuration
# ---------------------------
DATA_JSON_FILE = "input_data_small.json"         # New experiment data format (organized per weight)
PROGRESS_STORE_FILE = "progress_store.json"   # Persistent progress & scores storage

app = FastAPI()
data_store_lock = threading.RLock()  # Re-entrant lock for thread safety

# Adjust the path to your images directory:
images_dir = "/home/hassan/Desktop/pairwise_ranking/images"

# Mount the static directory at "/static"
if os.path.isdir(images_dir):
	app.mount("/static", StaticFiles(directory=images_dir), name="static")
else:
	raise ValueError(f"Images directory does not exist: {images_dir}")

# ---------------------------
# Load Experiment Definition (New Format)
# ---------------------------
# Expected JSON structure:
# {
#   "weights": ["w1", "w2", ..., "w10"],
#   "inputs": [
#       {
#         "id": "dp1",
#         "input": {
#             "text": "A scenic view of a mountain",
#             "image": "/static/input1.jpg"
#         }
#       },
#       {
#         "id": "dp2",
#         "input": {
#             "text": "A futuristic cityscape",
#             "image": "/static/input2.jpg"
#         }
#       }
#   ],
#   "outputs": {
#       "w1": ["/static/dp1_w1.jpg", "/static/dp2_w1.jpg"],
#       "w2": ["/static/dp1_w2.jpg", "/static/dp2_w2.jpg"],
#       ...
#       "w10": ["/static/dp1_w10.jpg", "/static/dp2_w10.jpg"]
#   }
# }

with open(DATA_JSON_FILE, "r") as f:
	experiment_data = json.load(f)

weights = experiment_data["weights"]
inputs_data = experiment_data["inputs"]
outputs = experiment_data["outputs"]

# ---------------------------
# Generate All Pairwise Tasks (Randomized Display per Rater)
# ---------------------------
# For each input (datapoint), and for every combination of two weights,
# create a task that shows the input along with the two outputs.
tasks = []
for i, inp in enumerate(inputs_data):
	for w1, w2 in itertools.combinations(weights, 2):
		tasks.append({
			"datapoint_id": inp["id"],
			"input": inp["input"],
			"left_weight": w1,
			"right_weight": w2,
			"left_output": outputs[w1][i],
			"right_output": outputs[w2][i],
		})

# ---------------------------
# Persistence: rater_sessions + aggregate_scores
# ---------------------------
# The progress file stores:
# {
#   "rater_sessions": {
#       "alice": {"order": [shuffled indices], "current_index": 3},
#       "bob": { ... }
#   },
#   "aggregate_scores": {"w1": 2, "w2": -1, ...}
# }

default_aggregate_scores = {w: 0 for w in weights}
default_rater_sessions = {}  # Will hold entries like: rater_id -> {"order": [...], "current_index": 0}

def load_progress():
	"""
	Loads rater_sessions and aggregate_scores from PROGRESS_STORE_FILE if it exists.
	Otherwise returns default values.
	"""
	if not os.path.exists(PROGRESS_STORE_FILE):
		return {"rater_sessions": default_rater_sessions,
				"aggregate_scores": default_aggregate_scores}
	with open(PROGRESS_STORE_FILE, "r") as f:
		data = json.load(f)
		# Ensure all weights are present in aggregate_scores
		stored_scores = data.get("aggregate_scores", {})
		for w in weights:
			if w not in stored_scores:
				stored_scores[w] = 0
		return {
			"rater_sessions": data.get("rater_sessions", {}),
			"aggregate_scores": stored_scores
		}

def save_progress(rater_sessions, aggregate_scores):
	"""
	Saves rater_sessions and aggregate_scores to PROGRESS_STORE_FILE in a thread-safe manner.
	"""
	with data_store_lock:
		data = {
			"rater_sessions": rater_sessions,
			"aggregate_scores": aggregate_scores
		}
		with open(PROGRESS_STORE_FILE, "w") as f:
			json.dump(data, f, indent=2)

# Load existing progress if any
progress_data = load_progress()
rater_sessions = progress_data["rater_sessions"]
aggregate_scores = progress_data["aggregate_scores"]

# ---------------------------
# FastAPI Endpoints
# ---------------------------

@app.get("/task", response_class=HTMLResponse)
async def get_task(rater_id: str):
	"""
	Returns the next pairwise comparison task for the given rater_id.
	For new raters, creates a randomized task order and initializes their progress.
	"""
	with data_store_lock:
		if rater_id not in rater_sessions or not isinstance(rater_sessions[rater_id], dict):
			# Fix: If the rater is stored as an integer, reset it to the correct format
			order = list(range(len(tasks)))
			random.shuffle(order)
			rater_sessions[rater_id] = {"order": order, "current_index": 0}
			save_progress(rater_sessions, aggregate_scores)

		session = rater_sessions[rater_id]  # Ensure session is now a dict
		current_index = session["current_index"]

	if current_index >= len(tasks):
		return HTMLResponse("<h3>All tasks completed. Thank you for your evaluation!</h3>")

	task_idx = session["order"][current_index]
	task = tasks[task_idx]

	# Build HTML page with responsive design.
	# A header "Select your favorite!" is shown above the two images.
	html_content = f"""
	<html>
	  <head>
		<title>Pairwise Comparison Task</title>
		<meta name="viewport" content="width=device-width, initial-scale=1.0">
		<style>
		  body {{
			font-family: Arial, sans-serif;
			margin: 20px;
		  }}
		  /* Make the image container tight around the image */
		  .image-container {{
			cursor: pointer;
			position: relative;
			display: inline-block;
		  }}
		  .image-container img {{
			display: block;
		  }}
		  /* Tighter selected border */
		  .image-container.selected {{
			border: 3px solid green;
		  }}
		  /* Heart overlay: shown when selected */
		  .image-container.selected::after {{
			content: "❤️";
			font-size: 1.5em;
			position: absolute;
			top: 5px;
			right: 5px;
			z-index: 100;
		  }}
		  /* Responsive layout: two items side-by-side on larger screens, stacked on mobile */
		  .flex-container {{
			display: flex;
			flex-wrap: wrap;
			justify-content: center;
			gap: 20px;
		  }}
		  .flex-item {{
			flex: 1 1 300px;
			text-align: center;
		  }}
		  img {{
			width: 100%;
			height: auto;
			max-width: 300px;
		  }}
		  /* Big, fat Submit button */
		  input[type="submit"] {{
			font-size: 1.5em;
			padding: 15px 30px;
			margin: 20px auto;
			display: block;
		  }}
		</style>
		<script>
		  function toggleSelection(side) {{
			var imgDiv = document.getElementById(side + "-img-div");
			var inputField = document.getElementById(side + "-selected");
			if (imgDiv.classList.contains("selected")) {{
			  imgDiv.classList.remove("selected");
			  inputField.value = "0";
			}} else {{
			  imgDiv.classList.add("selected");
			  inputField.value = "1";
			}}
		  }}
		</script>
	  </head>
	  <body>
		<h2 style="text-align: center;">Select your favorite!</h2>
		<h3 style="text-align: center;">Datapoint ID: {task['datapoint_id']}</h3>
		<div style="text-align: center;">
		  <h4>Input:</h4>
	"""
	# Show input text if available.
	if "text" in task["input"]:
		html_content += f"<p><strong>Prompt:</strong> {task['input']['text']}</p>"
	# Show input image if available.
	if "image" in task["input"]:
		html_content += f"<img src='{task['input']['image']}' alt='Input Image' style='max-width:300px;'/><br>"
	html_content += "</div><hr>"

	# Build the form with hidden fields to record selections.
	html_content += f"""
		<form action="/submit" method="post">
		  <input type="hidden" name="rater_id" value="{rater_id}">
		  <input type="hidden" name="datapoint_id" value="{task['datapoint_id']}">
		  <input type="hidden" name="left_weight" value="{task['left_weight']}">
		  <input type="hidden" name="right_weight" value="{task['right_weight']}">
		  <input type="hidden" id="left-selected" name="left_selected" value="0">
		  <input type="hidden" id="right-selected" name="right_selected" value="0">
		  <div class="flex-container">
			<div id="left-img-div" class="flex-item image-container" onclick="toggleSelection('left')">
			  <img src="{task['left_output']}" alt="Left Output"/>
			</div>
			<div id="right-img-div" class="flex-item image-container" onclick="toggleSelection('right')">
			  <img src="{task['right_output']}" alt="Right Output"/>
			</div>
		  </div>
		  <br>
		  <p style="text-align: center;">Click an image to toggle selection. You may select one, both, or none.</p>
		  <input type="submit" value="Submit">
		</form>
	  </body>
	</html>
	"""
	return HTMLResponse(content=html_content)


@app.post("/submit", response_class=HTMLResponse)
async def submit_rating(
	rater_id: str = Form(...),
	datapoint_id: str = Form(...),
	left_weight: str = Form(...),
	right_weight: str = Form(...),
	left_selected: str = Form(...),
	right_selected: str = Form(...)
):
	"""
	Receives the rater's selection for a given pair and applies scoring:
	  - Only left selected: left gets +1; right gets -1.
	  - Only right selected: right gets +1; left gets -1.
	  - Both selected: both get +1.
	  - Neither selected: both get -1.
	Advances the rater's session (using their randomized order) and persists progress.
	"""
	l_sel = int(left_selected)
	r_sel = int(right_selected)

	# Diagnostic prints:
	print("DEBUG: Rater:", rater_id)
	print("DEBUG: Datapoint:", datapoint_id)
	print("DEBUG: left_weight =", left_weight, ", right_weight =", right_weight)
	print("DEBUG: l_sel =", l_sel, ", r_sel =", r_sel)
	print("DEBUG: Current Scores (before):", aggregate_scores)

	with data_store_lock:
		if l_sel == 1 and r_sel == 0:
			aggregate_scores[left_weight] += 1
			aggregate_scores[right_weight] -= 1
		elif l_sel == 0 and r_sel == 1:
			aggregate_scores[left_weight] -= 1
			aggregate_scores[right_weight] += 1
		elif l_sel == 1 and r_sel == 1:
			aggregate_scores[left_weight] += 1
			aggregate_scores[right_weight] += 1
		elif l_sel == 0 and r_sel == 0:
			aggregate_scores[left_weight] -= 1
			aggregate_scores[right_weight] -= 1

		print("DEBUG: Updated Scores (after):", aggregate_scores)

		# Advance session for the rater (using their randomized order)
		rater_sessions[rater_id]["current_index"] += 1
		next_index = rater_sessions[rater_id]["current_index"]

		# Persist changes
		save_progress(rater_sessions, aggregate_scores)

	if next_index >= len(tasks):
		return HTMLResponse("<h3>All tasks completed. Thank you for your evaluation!</h3>")
	else:
		# Redirect to the next task
		return HTMLResponse(f"""
			<html>
			  <head>
				<meta http-equiv="refresh" content="0; url=/task?rater_id={rater_id}" />
			  </head>
			  <body>
				<p>Submission recorded. Loading next task...</p>
			  </body>
			</html>
		""")


@app.get("/results", response_class=JSONResponse)
async def get_results():
	"""
	Returns the aggregate scores across all weights in JSON format.
	"""
	return JSONResponse(content=aggregate_scores)


@app.get("/status", response_class=JSONResponse)
async def get_status(rater_id: str):
	"""
	Returns the progress (completed tasks) for the given rater.
	"""
	with data_store_lock:
		session = rater_sessions.get(rater_id, {"current_index": 0})
		progress = session.get("current_index", 0)
	total_tasks = len(tasks)
	return JSONResponse(content={"rater_id": rater_id, "progress": progress, "total_tasks": total_tasks})


# ---------------------------
# Main Entry Point
# ---------------------------
if __name__ == "__main__":
	uvicorn.run(app, host="0.0.0.0", port=8000)
