# TEO — Total Energy Optimizer

Git repository til versionsstyring af TEO-koden.

## 📦 Repository info

- **Location:** `/config/custom_components/teo/`
- **Branch:** master
- **Version:** Læses fra `/config/teo_algorithm_version.txt`

## 🔧 Vigtigste git-kommandoer

### Se status
```bash
cd /config/custom_components/teo
sudo git status
```

### Se historik
```bash
# Kort oversigt
sudo git log --oneline

# Detaljeret log med ændringer
sudo git log --stat

# Seneste 5 commits
sudo git log --oneline -5

# Se ændringer i specifik commit
sudo git show <commit-hash>
```

### Gem ændringer (commit)
```bash
# 1. Se hvad der er ændret
sudo git status

# 2. Tilføj ændrede filer
sudo git add .

# 3. Commit med beskrivende besked
sudo git commit -m "Beskrivelse af ændring"

# Eksempel med version:
VERSION=$(cat /config/teo_algorithm_version.txt)
sudo git commit -m "TEO v${VERSION} — rettelse af optimizer bug"
```

### Se ændringer før commit
```bash
# Se ikke-staged ændringer
sudo git diff

# Se staged ændringer (klar til commit)
sudo git diff --cached

# Se ændringer i specifik fil
sudo git diff coordinator.py
```

### Sammenlign commits
```bash
# Se ændringer siden sidste commit
sudo git diff HEAD~1

# Sammenlign to commits
sudo git diff <commit1> <commit2>

# Se filer der ændrede sig mellem commits
sudo git diff --name-only <commit1> <commit2>
```

### Fortryd ændringer (FARLIGT!)
```bash
# Fortryd ændringer i én fil (før add)
sudo git checkout -- <filnavn>

# Fortryd alle unstaged ændringer (før add)
sudo git checkout -- .

# Unstage en fil (efter add, før commit)
sudo git reset HEAD <filnavn>

# Fortryd sidste commit (BEHOLDER ændringer)
sudo git reset --soft HEAD~1

# Fortryd sidste commit (SLETTER ændringer - FARLIGT!)
sudo git reset --hard HEAD~1
```

### Genskab gammel version af fil
```bash
# Se fil fra specifik commit
sudo git show <commit-hash>:<filnavn>

# Genskab fil fra specifik commit
sudo git checkout <commit-hash> -- <filnavn>
```

### Søg i historik
```bash
# Find commits der ændrede specifik fil
sudo git log --oneline -- <filnavn>

# Søg efter tekst i commit-beskeder
sudo git log --grep="optimizer"

# Find hvornår en linje kode blev ændret
sudo git blame <filnavn>
```

## 📝 Anbefalet workflow

### Efter daglig calibration bump
```bash
cd /config/custom_components/teo
VERSION=$(cat /config/teo_algorithm_version.txt)
sudo git add .
sudo git commit -m "TEO v${VERSION} — auto bump efter daily calibration"
```

### Efter manuel kode-ændring
```bash
cd /config/custom_components/teo
sudo git status                    # Se hvad der er ændret
sudo git diff                      # Review ændringer
sudo git add .                     # Stage alle ændringer
sudo git commit -m "Fix: beskrivelse af rettelse"
```

### Før større ændringer
```bash
# Gem nuværende tilstand først
sudo git add .
sudo git commit -m "Checkpoint før [ændring]"

# Lav ændringer...
# Hvis det går galt:
sudo git reset --hard HEAD~1       # Tilbage til checkpoint
```

## 🔍 Nyttige aliaser (valgfri)

Tilføj til `~/.bashrc` eller `~/.zshrc`:
```bash
alias teo-status='cd /config/custom_components/teo && sudo git status'
alias teo-log='cd /config/custom_components/teo && sudo git log --oneline -10'
alias teo-diff='cd /config/custom_components/teo && sudo git diff'
```

## 📚 .gitignore

Følgende filer/mapper ignoreres automatisk:
- `__pycache__/` — Python cache
- `*.pyc` — Compiled Python files
- `*.db` — Database filer
- `*.log` — Log filer

## ⚠️ Vigtige noter

1. **Brug altid `sudo`** — Repository er ejet af root
2. **Commit regelmæssigt** — Efter hver betydelig ændring
3. **Beskrivende commit-beskeder** — Forklar HVAD og HVORFOR
4. **Test før commit** — Reload TEO og verificer at det virker
5. **ALDRIG force push** — Dette er et lokalt repo, men vær alligevel forsigtig

## 🆘 Hvis noget går galt

### "Jeg commitede forkert fil"
```bash
# Fjern fil fra sidste commit (BEHOLDER lokal fil)
sudo git rm --cached <filnavn>
sudo git commit --amend
```

### "Jeg vil se koden som den var i går"
```bash
# Find commit fra i går
sudo git log --since="yesterday" --oneline

# Se kode fra specifik commit
sudo git show <commit-hash>:<filnavn>
```

### "Jeg vil rulle tilbage til en tidligere version"
```bash
# 1. Find den gode commit
sudo git log --oneline

# 2. Genskab fra den commit (FARLIGT!)
sudo git reset --hard <commit-hash>

# 3. Reload TEO i Home Assistant
```

## 📖 Mere hjælp

```bash
# Git manual
man git

# Hjælp til specifik kommando
git <kommando> --help
```
