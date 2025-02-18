import { useEffect, useRef } from "react";

const VideoPlayer = ({ peerConnection }) => {
    const videoRef = useRef(null);

    useEffect(() => {
        if (!peerConnection) return;

        // Listen for remote track events
        peerConnection.ontrack = (event) => {
            console.log("Track event received:", event);

            if (videoRef.current) {
                videoRef.current.srcObject = event.streams[0];
                console.log("Video ref updated:", videoRef.current.srcObject);
            }
        };

    }, [peerConnection]);

    return (
        <video ref={videoRef} autoPlay playsInline className="chicken-viewport">
            <track kind="captions" label="Captions" />
        </video>
    );
};

export default VideoPlayer;
