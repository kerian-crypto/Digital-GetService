document.addEventListener('DOMContentLoaded', () => {
    const navbar = document.querySelector('.navbar');
    if (!navbar) {
        return;
    }

    window.addEventListener('scroll', () => {
        if (window.scrollY > 32) {
            navbar.classList.add('is-scrolled');
        } else {
            navbar.classList.remove('is-scrolled');
        }
    });
});
