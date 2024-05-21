# About

A modified version of [kiirkirjutaja](https://github.com/alumae/kiirkirjutaja) configured to transcribe audio streams
from [livesubs.ee](livesubs.ee) users.

# Original requirements

Since _pip install_ was unable to provide the required dependencies, the simplest solution is to create a new virtual
environment, enter a container of the original version's Docker image, locate the virtual environment created within and
manually copy the contents of the folder _python3.9/bin/site_packages_ over to the corresponding location of the new
environment.

You will also require the models and [online_speaker_change_detector](https://github.com/alumae/online_speaker_change_detector),
see the [original Dockerfile](https://github.com/alumae/kiirkirjutaja/blob/main/docker/Dockerfile) for installation
instructions or scavenge them from a working Docker container as well.

(In essence, if the new instance is set up as described by the Dockerfile, just like the Docker container, then it
should also work just like the Docker container.)

# Additional requirements

FastAPI and websockets as listed in _reqs2.txt_ (install using _pip install -r reqs2.txt_).

# Usage

Activate the new virtual environment and call _uvicorn kiirkirjutaja.main2:app --host 0.0.0.0_ in the root directory
of the project.