# 🐦‍⬛ Bird Live Stream - Quick Start Guide

## 📋 Prerequisites
* Docker installed on your system
* Docker Compose installed
* A webcam connected to your system
* Git installed

## 🚀 Getting Started
Clone and run the project with these simple commands:

```bash
git clone https://github.com/etiennegalea/bird-stream.git
cd bird-stream
docker-compose up --build
```

## 🌐 Access Points
| Service | URL/Port |
|---------|----------|
| Frontend Interface | `http://localhost:8050` |
| Backend Service | Port `8051` |
| TURN Server | Ports `3478`, `5349` |

## 📹 Key Features
* Real-time bird watching stream through WebRTC
* TURN server for NAT traversal
* Frontend web interface for viewing the stream

## 🛑 Stopping the Application
```bash
docker-compose down
```

## 🎉 Success!
Your bird watching stream is ready! Enjoy observing nature in real-time! 🦜
