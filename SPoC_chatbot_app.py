from flask import Flask, render_template, request, jsonify
import os
import subprocess
import threading
#import webbrowser

app = Flask(__name__)

QUESTIONS = [
    {"key": "input_meas_path", "prompt": "Enter input measurement folder path:", "type": "path"},
    {"key": "output_path", "prompt": "Enter output folder path:", "type": "path"},
    {"key": "system", "prompt": "Enter system name (e.g., ESP10CU):", "type": "text"},
    {"key": "project_description", "prompt": "Enter project description:", "type": "text"},
    {"key": "signal_list_path", "prompt": "Enter signal list CSV file path:", "type": "file"},
    {"key": "motor_parameter_evaluation", "prompt": "Enable Motor Parameter Evaluation? (1=Yes, 0=No):", "type": "bool"},
    {"key": "p_model_vs_sim_comparision", "prompt": "Enable P Model vs Sim Comparison? (1=Yes, 0=No):", "type": "bool"},
]

SESSIONS = {}

def validate_input(value, qtype):
    if not value or value.strip() == "":
        return False, "Input cannot be empty."
    
    if qtype == "path":
        # Normalize path for cross-platform compatibility
        normalized_path = os.path.normpath(value.strip())
        
        # For Azure/production environments, use a more direct approach
        try:
            # Try to access the path directly - this is more reliable than os.path.exists in some environments
            if os.path.isabs(normalized_path):
                test_path = normalized_path
            else:
                test_path = os.path.abspath(normalized_path)
            
            # Test actual access to the path
            if os.path.isdir(test_path):
                os.listdir(test_path)
            elif os.path.isfile(test_path):
                # If it's a file, just check if we can read it
                with open(test_path, 'r') as f:
                    pass
            else:
                # Path doesn't exist as file or directory
                # Check if parent directory exists for creating new files/dirs
                parent_dir = os.path.dirname(test_path)
                if parent_dir:
                    os.listdir(parent_dir)
                else:
                    return False, "Path does not exist and cannot be created."
            
        except FileNotFoundError:
            return False, "Path does not exist."
        except PermissionError:
            return False, "Path exists but is not accessible (permission denied)."
        except IsADirectoryError:
            return False, "Expected a file path but found a directory."
        except NotADirectoryError:
            return False, "Expected a directory path but found a file."
        except Exception as e:
            return False, f"Path validation error: {str(e)}"
    
    if qtype == "file":
        if not os.path.isfile(value):
            return False, "File does not exist."
        if not value.lower().endswith('.csv'):
            return False, "File must be a CSV."
        
        # Check file accessibility in production
        try:
            with open(value, 'r') as f:
                pass  # Just check if file can be opened
        except PermissionError:
            return False, "File exists but is not accessible (permission denied)."
        except Exception as e:
            return False, f"File accessibility error: {str(e)}"
    
    if qtype == "bool" and value not in ["0", "1"]:
        return False, "Enter 1 or 0."
    return True, ""

@app.route("/")
def index():
    return render_template("chatbot.html")

@app.route("/chat", methods=["POST"])
def chat():
    session_id = request.remote_addr
    user_msg = request.json.get("message", "").strip()
    state = SESSIONS.setdefault(session_id, {"step": 0, "inputs": {}, "result": None, "reports": [], "running": False})

    user_msg_lower = user_msg.lower()

    if user_msg_lower in ["help", "?"]:
        help_text = (
            "<b>SPoC Chatbot Help</b><br>"
            "<ul>"
            "<li>Type your inputs step by step as prompted.</li>"
            "<li><b>run</b>: Start the SPoC analysis after all inputs are collected.</li>"
            "<li><b>status</b>: Check the progress or result of the analysis.</li>"
            "<li><b>explain</b>: Get a link to the generated report and summary.</li>"
            "<li><b>reset</b>: Restart the session and clear all inputs.</li>"
            "<li><b>help</b>: Show this help message.</li>"
            "</ul>"
        )
        return jsonify({"response": help_text})

    if user_msg_lower in ["reset", "restart"]:
        SESSIONS[session_id] = {"step": 0, "inputs": {}, "result": None, "reports": [], "running": False}
        return jsonify({"response": QUESTIONS[0]["prompt"]})

    if state.get("running"):
        return jsonify({"response": "Analysis is running. Please wait..."})

    if state["step"] < len(QUESTIONS):
        q = QUESTIONS[state["step"]]
        valid, msg = validate_input(user_msg, q["type"])
        if not valid:
            return jsonify({"response": f"❌ {msg} {q['prompt']}"})
        if q["type"] == "bool":
            state["inputs"][q["key"]] = int(user_msg)
        else:
            state["inputs"][q["key"]] = user_msg
        state["step"] += 1
        if state["step"] < len(QUESTIONS):
            return jsonify({"response": QUESTIONS[state["step"]]["prompt"]})
        else:
            summary = "\n".join([f"{k}: {v}" for k, v in state["inputs"].items()])
            return jsonify({"response": f"All inputs collected:<br>{summary}<br><span style='color:#2d3e50;font-weight:bold;'>Type 'run' to start analysis.</span>"})

    if user_msg_lower == "run" and state["step"] == len(QUESTIONS):
        state["running"] = True
        def run_spoc():
            cmd = [
                "python", "spoc_main_UI_function.py",
                state["inputs"]["input_meas_path"],
                state["inputs"]["output_path"],
                state["inputs"]["system"],
                state["inputs"]["project_description"],
                state["inputs"]["signal_list_path"],
                str(state["inputs"]["motor_parameter_evaluation"]),
                str(state["inputs"]["p_model_vs_sim_comparision"])
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            state["result"] = proc.stdout if proc.returncode == 0 else proc.stderr
            htmls = []
            for f in os.listdir(state["inputs"]["output_path"]):
                if f.endswith(".html"):
                    htmls.append(os.path.join(state["inputs"]["output_path"], f))
            state["reports"] = htmls
            state["running"] = False
        threading.Thread(target=run_spoc).start()
        return jsonify({"response": "SPoC analysis started. Please wait and type 'status' to check progress."})

    if user_msg_lower == "status":
        if state.get("running"):
            return jsonify({"response": "Analysis is still running..."})
        if state["result"]:
            links = "\n".join([f"<a href='file:///{r}' target='_blank'>{os.path.basename(r)}</a>" for r in state["reports"]])
            return jsonify({"response": f"Analysis complete!\n{state['result']}\nReports:\n{links}"})
        return jsonify({"response": "No analysis has been run yet."})

    if user_msg_lower.startswith("explain"):
        if not state["reports"]:
            return jsonify({"response": "No report available to explain."})
        html_path = state["reports"][0]
        return jsonify({"response": f"Open the report: <a href='file:///{html_path}' target='_blank'>{os.path.basename(html_path)}</a> and review the summary table and plots. (Automated explanation can be added here.)"})

    return jsonify({"response": "Type 'help' for instructions or continue with your input."})

if __name__ == "__main__":
    app.run(host='0.0.0.0',port=8000,debug=True)
   #print('success')
    #import sys
    # # Only open browser if not running in Flask's reloader subprocess
    # if os.environ.get("WERKZEUG_RUN_MAIN") is None:
    #     print("Open http://localhost:5000 in your browser.")
    #     threading.Timer(1.5, lambda: webbrowser.open('http://localhost:5000')).start()
    # try:
    #     app.run(debug=True, host="localhost", port=5000)
    # except SystemExit:
    #     pass  # Prevent SystemExit exception from crashing the script
