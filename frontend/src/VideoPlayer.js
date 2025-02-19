import { useEffect, useRef, useState } from "react";

const VideoPlayer = ({ peerConnection }) => {
    const videoRef = useRef(null);
    const [streamState, isStreamState] = useState(false);

    console.log("Peer connection in VideoPlayer:", peerConnection);

    useEffect(() => {
        if (!peerConnection) {
            console.log("Peer connection is null");
            return;
        }
        else {
            console.log("Peer connection is NOT null: ", peerConnection);
    
            // Listen for remote track events
            peerConnection.ontrack = (event) => {
                console.log("Track event received:", event);
    
                if (videoRef.current) {
                    videoRef.current.srcObject = event.streams[0];
                    console.log("Video ref updated:", videoRef.current.srcObject);
                }
                else {
                    console.error("Video ref is null");
                }
            };
        }
        
        isStreamState(true);

    }, [peerConnection]);


    if (!streamState) {
        return (
            <div>Loading...</div>
        );
    }

    return (
        <video ref={videoRef} autoPlay playsInline className="chicken-viewport">
            <track kind="captions" label="Captions" />
        </video>
    );
};

export default VideoPlayer;
