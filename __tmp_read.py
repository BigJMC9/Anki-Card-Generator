from pathlib import Path 
lines=Path(r'Anki_Card_Generator/Anki_Card_Generator.py').read_text(encoding='utf-8').splitlines() 
for i in range(2775,2825): print(f'{i+1}: {lines[i]}') 
