#!/usr/bin/env python
# -*- coding: utf8 -*-
import argparse
from typing import List, Set
import nvsmi
import subprocess
import os
import time

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5000, help='port number')
parser.add_argument('--command', type=str)
args = parser.parse_args()

# Global variables
# available gpus are the gpus with gpu and memory usage less than 1%
available_gpus: List[nvsmi.GPU] = nvsmi.get_available_gpus()
command_occupied_gpu_ids: Set[int] = set()
process: subprocess.Popen = None

def start_process_on_gpus(command: str, gpu_ids: List[int]):
    """Start a process on the GPUs with the given IDs.
    """
    global process, command_occupied_gpu_ids
    # calculate the available gpus to be used
    command_occupied_gpu_ids = set(gpu_ids)
    print("Start command: [ {} ] on gpus: {}".format(command, sorted(gpu_ids)))

    # set the environment variable CUDA_VISIBLE_DEVICES
    copied_env = os.environ.copy()
    copied_env['CUDA_VISIBLE_DEVICES'] = ','.join([
        str(gpu_id) for gpu_id in sorted(gpu_ids)
    ])
    # start the process
    process = subprocess.Popen(
        command,
        shell=True,
        env=copied_env
    )

# update gpu info every 60 minutes
def update_gpu_info():
    global available_gpus
    available_gpus = list(nvsmi.get_available_gpus())
    print(f"* GPU info updated. Available GPUs: {[gpu.id for gpu in available_gpus]}")

sched = BackgroundScheduler(daemon=True)
sched.add_job(update_gpu_info, 'interval', minutes=60)
sched.start()

app = Flask(__name__)

@app.route("/gpu", methods=["POST"])
def set_occupied():
    """Set the GPU to occupied.
    
    Request body:
    {
        "command": "set_occupied",
        "gpu_ids": ["0", "1"]
    }
    """
    global available_gpus, command_occupied_gpu_ids
    if request.method == 'POST':
        posted_data = request.get_json()
        if posted_data['command'] == 'set_occupied':
            gpu_ids_occupied_by_others: List[str] = posted_data['gpu_ids']
            
            # kill the process if it is using the gpus to be occupied
            if process is not None:
                print(f"- Request Set Occupied GPUs: {gpu_ids_occupied_by_others}")
                print(f"- Current Command Occupied GPUs: {command_occupied_gpu_ids}")
                if any([
                    gpu_id in command_occupied_gpu_ids
                    for gpu_id in gpu_ids_occupied_by_others
                ]):
                    print(
                        f"Process is using some of the GPUs "
                        f"to be occupied {gpu_ids_occupied_by_others}, kill the process."
                    )
                    process.kill()
                    # wait for the process to free the gpus
                    time.sleep(1)

            # update gpu info and get the available gpus
            update_gpu_info()
            available_gpus = [
                gpu 
                for gpu in available_gpus 
                if gpu.id not in gpu_ids_occupied_by_others
            ]

            # start the process on the available gpus
            if len(available_gpus) > 0:
                start_process_on_gpus(args.command, [gpu.id for gpu in available_gpus])
                return jsonify({
                    'status': 'success',
                    'message': 'Use currently available GPUs: {}'.format(
                        [gpu.id for gpu in available_gpus]
                    )
                })
            else:
                return jsonify({
                    'status': 'success',
                    'message': 'No available GPUs - process will not started'
                })

@app.route("/gpu", methods=["GET"])
def get_available_gpus():
    """Get the available GPUs.
    """
    return jsonify([gpu.id for gpu in available_gpus])

# start the command in a subprocess
start_process_on_gpus(args.command, [gpu.id for gpu in available_gpus])

# start the flask app
app.run(debug=True)
