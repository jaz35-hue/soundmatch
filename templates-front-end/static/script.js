// Universal hamburger menu toggle function
// This will only run if no inline toggleMenu is defined
(function() {
    // Wait for DOM to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initHamburgerMenu);
    } else {
        initHamburgerMenu();
    }
    
    function initHamburgerMenu() {
        // Only initialize if toggleMenu is not already defined
        if (typeof window.toggleMenu !== 'undefined') {
            return; // Inline function exists, don't override
        }
        
        const menu = document.querySelector('.menu') || document.getElementById('navMenu');
        const hamburger = document.querySelector('.hamburger');
        
        if (!menu || !hamburger) {
            return; // Elements don't exist on this page
        }
        
        const menuIcon = hamburger.querySelector('.menuIcon');
        const closeIcon = hamburger.querySelector('.closeIcon');
        const menuItems = document.querySelectorAll(".menuItem");
        
        window.toggleMenu = function() {
            if (!menu || !hamburger) return;
            
            const isOpen = menu.classList.contains('showMenu');
            
            if (isOpen) {
                menu.classList.remove('showMenu');
                if (closeIcon) closeIcon.style.display = 'none';
                if (menuIcon) menuIcon.style.display = 'flex';
            } else {
                menu.classList.add('showMenu');
                if (closeIcon) closeIcon.style.display = 'flex';
                if (menuIcon) menuIcon.style.display = 'none';
            }
        };
        
        // Add click handler to hamburger
        hamburger.addEventListener('click', function(e) {
            e.stopPropagation();
            window.toggleMenu();
        });
        
        // Close menu when clicking menu items
        menuItems.forEach(function(menuItem) {
            menuItem.addEventListener('click', function() {
                setTimeout(window.toggleMenu, 100);
            });
        });
        
        // Close menu when clicking outside
        document.addEventListener('click', function(event) {
            if (menu && hamburger && 
                !menu.contains(event.target) && 
                !hamburger.contains(event.target) &&
                menu.classList.contains('showMenu')) {
                window.toggleMenu();
            }
        });
    }
})();