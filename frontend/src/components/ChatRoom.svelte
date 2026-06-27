<script>
  import { onDestroy, afterUpdate } from 'svelte';
  import '../styles/ChatRoom.css';
  import { getApiBaseUrl } from '../utils.js';

  export let onNewMessage = () => {};
  export let isChatVisible = true;

  let messages = [];
  let newMessage = '';
  let username = '';
  let isUsernameSet = false;
  let ws = null;
  let messagesEndEl;

  function connectChat() {
    if (ws) ws.close();

    const chatWs = new WebSocket(`${getApiBaseUrl(true)}/chat?username=${encodeURIComponent(username)}`);

    chatWs.onmessage = (event) => {
      const data = JSON.parse(event.data);

      onNewMessage();

      const messageDate = new Date(data.timestamp);
      const now = new Date();
      if (
        messageDate.getDate() !== now.getDate() ||
        messageDate.getMonth() !== now.getMonth() ||
        messageDate.getFullYear() !== now.getFullYear()
      ) {
        const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
        const dateStr = `${messageDate.getDate()} ${months[messageDate.getMonth()]} ${messageDate.getFullYear()}`;
        messages = [...messages, { type: 'system', text: dateStr, timestamp: messageDate.getTime() }];
      }

      if (data.type === 'history') {
        messages = data.messages.filter(msg => msg.type !== 'system');
      } else if (data.type === 'message') {
        messages = [...messages, data];
      } else if (data.type === 'system' && !data.text.includes(username)) {
        messages = [...messages, data];
      }
    };

    chatWs.onerror = (err) => console.error('Chat WebSocket error:', err);

    ws = chatWs;
  }

  afterUpdate(() => {
    if (isChatVisible && messagesEndEl) {
      messagesEndEl.scrollIntoView({ behavior: 'smooth' });
    }
  });

  function handleSendMessage(e) {
    e.preventDefault();
    if (!newMessage.trim() || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ username, text: newMessage, timestamp: new Date().toISOString() }));
    newMessage = '';
  }

  function handleSetUsername(e) {
    e.preventDefault();
    isUsernameSet = true;
    connectChat();
  }

  function getMessageClass(msg) {
    if (msg.type === 'system') return 'system';
    if (msg.username === username) return 'me';
    return 'user';
  }

  onDestroy(() => {
    if (ws) ws.close();
  });
</script>

{#if !isUsernameSet}
  <div class="chat-container">
    <form on:submit={handleSetUsername} class="username-form">
      <input
        type="text"
        bind:value={username}
        placeholder="Enter your username"
        maxlength="20"
      />
      <button type="submit">Join Chat</button>
    </form>
  </div>
{:else}
  <div class="chat-messages">
    {#each messages as msg (`${msg.username}-${msg.timestamp}`)}
      <div class="message {getMessageClass(msg)}">
        {#if msg.type === 'system'}
          <span class="message-text">{msg.text}</span>
        {:else}
          <div class="message-line">
            <span class="timestamp">
              {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
            <div class="message-content">
              <span class="username">{msg.username}: </span>
              <span class="message-text">{msg.text}</span>
            </div>
          </div>
        {/if}
      </div>
    {/each}
    <div bind:this={messagesEndEl}></div>
  </div>
  <form on:submit={handleSendMessage} class="message-form">
    <input
      type="text"
      bind:value={newMessage}
      placeholder="Type a message..."
      maxlength="255"
      autofocus
    />
    <button type="submit">Send</button>
  </form>
{/if}
