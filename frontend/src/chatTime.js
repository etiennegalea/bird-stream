export function formatChatTime(timestamp, locales = []) {
  return new Date(timestamp).toLocaleTimeString(locales, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
}
