import React, { useState, useEffect, useRef } from 'react';
import '../styles/ChatRoom.css';

function ChatRoom() {
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState('');
  const [username, setUsername] = useState('');
  const [isUsernameSet, setIsUsernameSet] = useState(false);
  const messagesEndRef = useRef(null);
  const [ws, setWs] = useState(null);

  // Initialize WebSocket connection
  useEffect(() => {
    if (isUsernameSet) {
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      const chatWs = new WebSocket(`${protocol}://localhost:8000/chat?username=${encodeURIComponent(username)}`);

      chatWs.onopen = () => {
        console.log("Chat WebSocket connection established");
      };

      chatWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log("Received message:", data);
        if (data.type === "history") {
          setMessages(data.messages.filter(msg => msg.type !== "system"));
        }
        else if (data.type === "message") {
          setMessages(prevMessages => [...prevMessages, data]);
        }
        else if (data.type === "system" && !data.text.includes(username)) {
          setMessages(prevMessages => [...prevMessages, data]);
        }
      };

      chatWs.onerror = (error) => {
        console.error("Chat WebSocket error:", error);
      };

      chatWs.onclose = () => {
        console.log("Chat WebSocket connection closed");
      };

      setWs(chatWs);

      return () => {
        if (chatWs) chatWs.close();
      };
    }
  }, [username, isUsernameSet]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    console.log("Messages updated:", messages);
  }, [messages]);

  const handleSendMessage = (e) => {
    e.preventDefault();
    if (newMessage.trim() === '') return;

    const messageData = {
      username: username,
      text: newMessage,
      timestamp: new Date().toISOString()
    };

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(messageData));
      setNewMessage('');
    }
  };

  const handleSetUsername = (e) => {
    e.preventDefault();
    if (username.trim() !== '') {
      setIsUsernameSet(true);
    }
  };

  if (!isUsernameSet) {
    return (
      <div className="chat-container">
        <form onSubmit={handleSetUsername} className="username-form">
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Enter your username"
            maxLength={20}
            required
          />
          <button type="submit">Join Chat</button>
        </form>
      </div>
    );
  }

  function getMessageClass(msg, currentUsername) {
    if (msg.type === 'system') {
      return 'system'
    }
    else if (msg.username === currentUsername) {
      return 'me'
    }
    return 'user'
  }

  return (
    <>
      <div className="chat-messages">
        {messages.map((msg, index) => (
          <div key={`${msg.username}-${msg.timestamp}`} className={`message ${getMessageClass(msg, username)}`}>
            <span className="username">{msg.username}</span>
            <span className="message-text">{msg.text}</span>
            {msg.type === 'system' ? '' : <span className="timestamp">{msg.timestamp}</span>}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      <form onSubmit={handleSendMessage} className="message-form">
        <input
          type="text"
          value={newMessage}
          onChange={(e) => setNewMessage(e.target.value)}
          placeholder="Type a message..."
          maxLength={255}
        />
        <button type="submit">Send</button>
      </form>
    </>
  );
}

export default ChatRoom;
