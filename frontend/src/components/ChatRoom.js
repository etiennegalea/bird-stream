import React, { useState, useEffect, useRef } from 'react';
import '../styles/ChatRoom.css';
import DOMPurify from 'dompurify';
import { getApiBaseUrl } from '../utils';

function ChatRoom({ onNewMessage }) {
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState('');
  const [username, setUsername] = useState('');
  const [isUsernameSet, setIsUsernameSet] = useState(false);
  const messagesEndRef = useRef(null);
  const [ws, setWs] = useState(null);

  const onNewMessageRef = useRef(onNewMessage);

  useEffect(() => {
    onNewMessageRef.current = onNewMessage;
  }, [onNewMessage]);

  // Initialize WebSocket connection
  useEffect(() => {
    if (isUsernameSet) {
      const chatWs = new WebSocket(`${getApiBaseUrl(true)}/chat?username=${encodeURIComponent(username)}`);

      chatWs.onopen = () => {
        console.log("Chat WebSocket connection established");
      };

      chatWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log("Received message:", data);

        // Notify parent component about new message (if it's not from history)
        // if (data.type === "message" && onNewMessage && typeof onNewMessage === 'function') {
        onNewMessageRef.current();
        console.log("New message received, calling onNewMessage");
        // }

        // Check if the date is different from current date
        const messageDate = new Date(data.timestamp);
        const currentDate = new Date();
        
        if (messageDate.getDate() !== currentDate.getDate() || 
            messageDate.getMonth() !== currentDate.getMonth() || 
            messageDate.getFullYear() !== currentDate.getFullYear()) {
          const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
          const dateString = `${messageDate.getDate()} ${months[messageDate.getMonth()]} ${messageDate.getFullYear()}`;
          setMessages(prevMessages => [...prevMessages, { type: "system", text: dateString, timestamp: messageDate.getTime() }]);
        }

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
    // Only scroll if the chat is visible
    if (!document.querySelector('.chat-section').classList.contains('chat-hidden')) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
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
            {msg.type === 'system' 
              ? <span className="message-text">{DOMPurify.sanitize(msg.text)}</span>
              : (
                <div className="message-line">
                  <span className="timestamp">{new Date(msg.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                  <div className="message-content">
                    <span className="username">{msg.username}: </span>
                    <span className="message-text">{DOMPurify.sanitize(msg.text)}</span>
                  </div>
                </div>
              )
            }
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
