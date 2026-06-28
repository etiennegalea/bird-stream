export const getApiBaseUrl = (ws = false) => {
  const protocol = ws
    ? (window.location.protocol === 'https:' ? 'wss' : 'ws')
    : (window.location.protocol === 'https:' ? 'https' : 'http');

  return `${protocol}://${import.meta.env.VITE_API_URL}`;
};

export const getTurnServers = () => {
  const username = import.meta.env.VITE_OPENRELAY_TURN_USERNAME;
  const credential = import.meta.env.VITE_OPENRELAY_TURN_CREDENTIAL;

  if (!username || !credential) {
    console.warn('TURN server credentials not found in environment variables');
    return [];
  }

  return [
    {
      urls: [
        'turn:global.relay.metered.ca:80?transport=udp',
        'turn:global.relay.metered.ca:443?transport=udp'
      ],
      username,
      credential
    }
  ];
};
