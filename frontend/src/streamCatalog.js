export function chooseStreamPath(streams, currentPath = null, savedPath = null) {
  const available = (streams || []).filter((stream) => stream.available);
  if (available.some((stream) => stream.path === currentPath)) return currentPath;
  if (available.some((stream) => stream.path === savedPath)) return savedPath;
  return available[0]?.path || null;
}

export function streamUrls(base, path) {
  if (!path) throw new Error('A stream path is required');
  const encoded = encodeURIComponent(path);
  return {
    whep: `${base}/${encoded}/whep`,
    hls: `${base}/hls/${encoded}/index.m3u8`,
  };
}
