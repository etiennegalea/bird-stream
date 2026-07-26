export function availableStreams(streams) {
  return (streams || []).filter((stream) => stream.available && stream.path);
}

export function chooseMainStreamPath(streams, currentPath = null) {
  const available = availableStreams(streams);
  if (available.some((stream) => stream.path === currentPath)) {
    return currentPath;
  }
  return available[0]?.path || null;
}

export function groupStreamsByDevice(streams) {
  const groups = new Map();
  for (const stream of availableStreams(streams)) {
    if (!groups.has(stream.pi_id)) {
      groups.set(stream.pi_id, { pi_id: stream.pi_id, streams: [] });
    }
    groups.get(stream.pi_id).streams.push(stream);
  }
  return [...groups.values()];
}

export function streamUrls(base, path) {
  if (!path) throw new Error('A stream path is required');
  const encoded = encodeURIComponent(path);
  return {
    whep: `${base}/${encoded}/whep`,
    hls: `${base}/hls/${encoded}/index.m3u8`,
  };
}
