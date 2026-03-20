(() => {
    const passwordInput = document.getElementById('regPassword');
    const strengthLabel = document.getElementById('passwordStrength');
    const phoneInput = document.getElementById('regPhone');
    const phoneDetect = document.getElementById('phoneDetect');

    const lang = (document.documentElement.lang || 'fr').toLowerCase();
    const labels = {
        fr: {
            weak: 'Faible',
            medium: 'Moyen',
            good: 'Bon',
            strong: 'Fort',
            strength: 'Force du mot de passe',
            phone: 'Detection du numero',
            cm: 'Cameroun',
            fr: 'France',
            de: 'Allemagne',
            us: 'USA/Canada',
            local: 'Local',
            unknown: 'Inconnu',
        },
        en: {
            weak: 'Weak',
            medium: 'Medium',
            good: 'Good',
            strong: 'Strong',
            strength: 'Password strength',
            phone: 'Phone detection',
            cm: 'Cameroon',
            fr: 'France',
            de: 'Germany',
            us: 'USA/Canada',
            local: 'Local',
            unknown: 'Unknown',
        },
        de: {
            weak: 'Schwach',
            medium: 'Mittel',
            good: 'Gut',
            strong: 'Stark',
            strength: 'Passwortstarke',
            phone: 'Nummernerkennung',
            cm: 'Kamerun',
            fr: 'Frankreich',
            de: 'Deutschland',
            us: 'USA/Kanada',
            local: 'Lokal',
            unknown: 'Unbekannt',
        },
    };

    const dict = labels[lang] || labels.fr;

    const passwordStrength = (value) => {
        let score = 0;
        if (value.length >= 8) score += 1;
        if (/[A-Z]/.test(value)) score += 1;
        if (/[a-z]/.test(value)) score += 1;
        if (/[0-9]/.test(value)) score += 1;
        if (/[^A-Za-z0-9]/.test(value)) score += 1;
        return score;
    };

    const strengthText = (score) => {
        if (score <= 2) return dict.weak;
        if (score <= 3) return dict.medium;
        if (score <= 4) return dict.good;
        return dict.strong;
    };

    const detectPhone = (raw) => {
        const value = raw.replace(/\s+/g, '');
        if (/^\+237/.test(value)) return dict.cm;
        if (/^\+33/.test(value)) return dict.fr;
        if (/^\+49/.test(value)) return dict.de;
        if (/^\+1/.test(value)) return dict.us;
        if (/^0\d{8,}/.test(value)) return dict.local;
        return dict.unknown;
    };

    if (passwordInput && strengthLabel) {
        passwordInput.addEventListener('input', () => {
            const score = passwordStrength(passwordInput.value);
            strengthLabel.textContent = `${dict.strength}: ${strengthText(score)}`;
        });
    }

    if (phoneInput && phoneDetect) {
        phoneInput.addEventListener('input', () => {
            phoneDetect.textContent = `${dict.phone}: ${detectPhone(phoneInput.value)}`;
        });
    }
})();
