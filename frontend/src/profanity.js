// Client-side display masking only. The backend always receives and stores raw text.
// Keep variants aligned with backend/services/profanity_service.py.
const variants = [
  // English
  'motherfuckers', 'motherfucker', 'bullshit', 'fuckers', 'fucking', 'fucked',
  'fucker', 'fucks', 'fuck', 'assholes', 'asshole', 'bastards', 'bastard',
  'bitches', 'bitch', 'shitty', 'shits', 'shit', 'wankers', 'wanker',
  'whores', 'whore', 'cunts', 'cunt', 'dicks', 'dick', 'cocks', 'cock',
  'pissed', 'piss', 'sluts', 'slut',
  // Maltese and common unaccented spellings
  'għoxx', 'ghoxx', 'qaħba', 'qahba', 'ħara', 'hara', 'żobb', 'zobb',
  'foxx', 'sorm', 'liba', 'ostja',
];

const escaped = variants
  .sort((a, b) => b.length - a.length)
  .map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));

const profanityPattern = new RegExp(`(^|[^\\p{L}\\p{N}_])(${escaped.join('|')})(?=$|[^\\p{L}\\p{N}_])`, 'giu');

export function censorProfanity(text) {
  if (typeof text !== 'string' || !text) return text;
  return text.replace(profanityPattern, (_, prefix, word) => `${prefix}${'*'.repeat([...word].length)}`);
}
