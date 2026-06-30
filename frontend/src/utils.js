const _ADJECTIVES = [
  'ancient', 'bold', 'brave', 'bright', 'brisk', 'calm', 'clever', 'crispy',
  'cunning', 'dark', 'daring', 'eager', 'fancy', 'fierce', 'fiery', 'fluffy',
  'fuzzy', 'gentle', 'golden', 'grumpy', 'hidden', 'hungry', 'icy', 'jolly',
  'keen', 'lazy', 'loud', 'lucky', 'mighty', 'misty', 'nimble', 'noble',
  'noisy', 'pale', 'plump', 'proud', 'quick', 'quiet', 'regal', 'rusty',
  'sassy', 'secret', 'shiny', 'silent', 'silver', 'sleek', 'sneaky', 'soft',
  'spry', 'stout', 'sunny', 'swift', 'tawny', 'tiny', 'velvet', 'vivid',
  'wild', 'wise', 'zippy', 'fattest', 'sexy', 'silly', 'crazy', 'wacky', 'funky',
  'groovy', 'freaky', 'weird', 'quirky', 'zany', 'bizarre', 'witty', 'sassy', 'spunky', 'snazzy', 'jazzy',
  'fabulous', 'fantastic', 'fierce', 'flamboyant', 'flirty', 'foxy', 'funky',
  'glamorous', 'groovy', 'hip', 'hilarious', 'hysterical', 'kooky', 'lively',
  'ludicrous', 'nutty', 'outrageous', 'peculiar', 'playful', 'quirky',
  'ridiculous', 'sassy', 'silly', 'spunky', 'strange', 'sultry', 'swanky',
  'wacky', 'wild'
];

const _BIRDS = [
  'albatross', 'avocet', 'bittern', 'bunting', 'buzzard', 'canary', 'cardinal',
  'condor', 'coot', 'crane', 'crow', 'cuckoo', 'dove', 'duck', 'eagle',
  'egret', 'falcon', 'finch', 'flamingo', 'gannet', 'goose', 'grebe',
  'grouse', 'guillemot', 'hawk', 'heron', 'hoopoe', 'ibis', 'jackdaw', 'jay',
  'kestrel', 'kingfisher', 'kite', 'lark', 'magpie', 'mallard', 'martin',
  'nightjar', 'nuthatch', 'oriole', 'osprey', 'owl', 'partridge', 'pelican',
  'petrel', 'pheasant', 'pigeon', 'puffin', 'quail', 'raven', 'robin',
  'rook', 'siskin', 'skylark', 'snipe', 'sparrow', 'starling', 'stork',
  'swift', 'teal', 'tern', 'thrush', 'toucan', 'wagtail', 'warbler', 'wren',
  'woodpecker', 'wren', 'vulture', 'oriole', 'parrot', 'cockatoo', 'macaw',
  'cockatiel', 'budgerigar', 'lovebird', 'finch', 'canary', 'dove', 'pigeon',
  'quail', 'pheasant', 'peacock', 'turkey', 'chicken', 'rooster', 'hen',
  'sparrowhawk', 'buzzard', 'kestrel', 'falcon', 'eagle', 'osprey',
  'harrier', 'kite', 'vulture', 'condor', 'albatross', 'petrel', 'shearwater',
  'gannet', 'booby', 'cormorant', 'pelican', 'stork', 'heron', 'egret',
  'bittern', 'ibis', 'spoonbill'
];

export const generateBirdUsername = () => {
  const adj = _ADJECTIVES[Math.floor(Math.random() * _ADJECTIVES.length)];
  const bird = _BIRDS[Math.floor(Math.random() * _BIRDS.length)];
  return adj + bird;
};

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
