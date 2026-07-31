// Client-side display masking only. The backend always receives and stores raw text.
// Keep variants aligned with backend/services/profanity_service.py.
const variants = [
  // English
  'motherfuckers', 'motherfucker', 'fuckfaces', 'fuckface', 'fuckers', 'fucking',
  'fucked', 'fucker', 'fucks', 'fuck', 'f*ck', 'fck', 'fuk', 'phuck',
  'bullshit', 'shitheads', 'shithead', 'shitty', 'shits', 'shit', 'sh1t',
  'bitches', 'bitch', 'b1tch', 'bastards', 'bastard', 'assholes', 'asshole',
  'a$$holes', 'a$$hole', 'asses', 'ass', 'arseholes', 'arsehole', 'arses', 'arse',
  'dickheads', 'dickhead', 'dicks', 'dick', 'cocks', 'cock', 'cunts', 'cunt',
  'pissing', 'pisses', 'pissed', 'piss', 'wankers', 'wanking', 'wanked',
  'wanks', 'wanker', 'wank', 'whores', 'whore', 'sluts', 'slut',
  'goddamned', 'goddamn', 'damning', 'dammit', 'damned', 'damns', 'damn',
  'crappy', 'craps', 'crap', 'bollocks', 'bollock', 'buggering', 'buggered',
  'buggers', 'bugger', 'douchebags', 'douchebag', 'douches', 'douche',
  'jackasses', 'jackass', 'pricks', 'prick', 'twats', 'twat', 'pussies', 'pussy', 'sonofabitch',
  // Abusive slurs
  'niggers', 'nigger', 'niggas', 'nigga', 'faggots', 'faggot', 'fags', 'fag',
  'retarded', 'retards', 'retard', 'chinks', 'chink', 'spics', 'spic',
  'kikes', 'kike', 'wetbacks', 'wetback', 'trannies', 'tranny',
  // Maltese and common unaccented spellings
  'għoxxkom', 'ghoxxkom', 'għoxxhom', 'ghoxxhom', 'għoxxha', 'ghoxxha',
  'għoxxna', 'ghoxxna', 'għoxxok', 'ghoxxok', 'għoxxi', 'ghoxxi',
  'għoxxu', 'ghoxxu', 'għoxx', 'ghoxx', 'għoss', 'ghoss', 'oxx',
  'qaħba', 'qahba', 'qħab', 'qhab', 'qoħob', 'qohob', 'ħara', 'hara',
  'żobbkom', 'zobbkom', 'żobbhom', 'zobbhom', 'żobbha', 'zobbha',
  'żobbna', 'zobbna', 'żobbok', 'zobbok', 'żobbi', 'zobbi', 'żobbu',
  'zobbu', 'żobb', 'zobb', 'żbubi', 'zbubi', 'żbub', 'zbub', 'foxx', 'liba',
  'ostja', 'nejka', 'żabbab', 'zabbab', 'żagħka', 'zaghka', 'żoċċ', 'zocc', 'pufta', 'pufti',
];

const escaped = variants
  .sort((a, b) => b.length - a.length)
  .map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));

const profanityPattern = new RegExp(`(^|[^\\p{L}\\p{N}_])(${escaped.join('|')})(?=$|[^\\p{L}\\p{N}_])`, 'giu');

export function censorProfanity(text) {
  if (typeof text !== 'string' || !text) return text;
  return text.replace(profanityPattern, (_, prefix, word) => `${prefix}${'*'.repeat([...word].length)}`);
}
