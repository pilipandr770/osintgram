/**
 * Instagram OSINT - JavaScript Functions
 * UI interactions and utilities
 */

// ============ MOBILE MENU ============

function toggleMobileMenu() {
    const menu = document.querySelector('.navbar-menu');
    menu.classList.toggle('active');
}

// Close mobile menu when clicking outside
document.addEventListener('click', function(event) {
    const menu = document.querySelector('.navbar-menu');
    const toggle = document.querySelector('.navbar-toggle');
    
    if (menu && toggle && !menu.contains(event.target) && !toggle.contains(event.target)) {
        menu.classList.remove('active');
    }
});

// ============ ALERTS AUTO-DISMISS ============

document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-10px)';
            setTimeout(function() {
                alert.remove();
            }, 300);
        }, 5000);
    });
});

// ============ FORM VALIDATION ============

// Password confirmation validation
document.addEventListener('DOMContentLoaded', function() {
    const passwordInput = document.getElementById('password');
    const confirmInput = document.getElementById('password_confirm');
    
    if (passwordInput && confirmInput) {
        confirmInput.addEventListener('input', function() {
            if (confirmInput.value !== passwordInput.value) {
                confirmInput.setCustomValidity('Пароли не совпадают');
            } else {
                confirmInput.setCustomValidity('');
            }
        });
        
        passwordInput.addEventListener('input', function() {
            if (confirmInput.value && confirmInput.value !== passwordInput.value) {
                confirmInput.setCustomValidity('Пароли не совпадают');
            } else {
                confirmInput.setCustomValidity('');
            }
        });
    }
});

// ============ COMPETITOR USERNAMES PROCESSING ============

document.addEventListener('DOMContentLoaded', function() {
    const textarea = document.getElementById('competitor_usernames');
    
    if (textarea) {
        // Clean up input on blur
        textarea.addEventListener('blur', function() {
            let value = this.value;
            // Remove @ symbols and extra spaces
            let usernames = value.split(',').map(function(u) {
                return u.trim().replace(/^@/, '');
            }).filter(function(u) {
                return u.length > 0;
            });
            
            // Update textarea with cleaned values
            this.value = usernames.join(', ');
        });
        
        // Show count of usernames
        textarea.addEventListener('input', function() {
            let usernames = this.value.split(',').filter(function(u) {
                return u.trim().length > 0;
            });
            
            let countEl = document.getElementById('username-count');
            if (!countEl) {
                countEl = document.createElement('small');
                countEl.id = 'username-count';
                countEl.style.display = 'block';
                countEl.style.marginTop = '5px';
                this.parentNode.appendChild(countEl);
            }
            
            if (usernames.length > 0) {
                countEl.textContent = `${usernames.length} аккаунт(ов) для парсинга`;
                countEl.style.color = usernames.length > 7 ? '#ED4956' : '#8E8E8E';
            } else {
                countEl.textContent = '';
            }
        });
    }
});

// ============ FILE INPUT PREVIEW ============

document.addEventListener('DOMContentLoaded', function() {
    const fileInputs = document.querySelectorAll('input[type="file"]');
    
    fileInputs.forEach(function(input) {
        input.addEventListener('change', function() {
            const files = this.files;
            let previewContainer = this.parentNode.querySelector('.file-preview');
            
            if (!previewContainer) {
                previewContainer = document.createElement('div');
                previewContainer.className = 'file-preview';
                previewContainer.style.marginTop = '10px';
                previewContainer.style.display = 'flex';
                previewContainer.style.flexWrap = 'wrap';
                previewContainer.style.gap = '10px';
                this.parentNode.appendChild(previewContainer);
            }
            
            previewContainer.innerHTML = '';
            
            Array.from(files).forEach(function(file) {
                if (file.type.startsWith('image/')) {
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        const img = document.createElement('img');
                        img.src = e.target.result;
                        img.style.width = '80px';
                        img.style.height = '80px';
                        img.style.objectFit = 'cover';
                        img.style.borderRadius = '8px';
                        previewContainer.appendChild(img);
                    };
                    reader.readAsDataURL(file);
                } else {
                    const div = document.createElement('div');
                    div.textContent = file.name;
                    div.style.padding = '10px';
                    div.style.background = '#F0F0F0';
                    div.style.borderRadius = '8px';
                    div.style.fontSize = '0.9rem';
                    previewContainer.appendChild(div);
                }
            });
        });
    });
});

// ============ LOADING STATES ============

function showLoading(button, text = 'Загрузка...') {
    button.disabled = true;
    button.dataset.originalText = button.textContent;
    button.textContent = text;
    button.style.opacity = '0.7';
}

function hideLoading(button) {
    button.disabled = false;
    button.textContent = button.dataset.originalText || 'Submit';
    button.style.opacity = '1';
}

// Add loading state to forms with long operations
document.addEventListener('DOMContentLoaded', function() {
    const parseForm = document.querySelector('.parse-form');
    if (parseForm) {
        parseForm.addEventListener('submit', function() {
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                showLoading(submitBtn, '⏳ Парсинг...');
            }
        });
    }
    
    const publishForm = document.querySelector('.publish-form');
    if (publishForm) {
        publishForm.addEventListener('submit', function() {
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                showLoading(submitBtn, '⏳ Публикация...');
            }
        });
    }
    
    const accountForm = document.querySelector('.account-form');
    if (accountForm) {
        accountForm.addEventListener('submit', function() {
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                showLoading(submitBtn, '⏳ Проверка...');
            }
        });
    }
});

// ============ TABLE SORTING ============

function sortTable(tableId, columnIndex, isNumeric = false) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    
    const sortedRows = rows.sort(function(a, b) {
        const aValue = a.cells[columnIndex].textContent.trim();
        const bValue = b.cells[columnIndex].textContent.trim();
        
        if (isNumeric) {
            return parseInt(bValue) - parseInt(aValue);
        }
        return aValue.localeCompare(bValue);
    });
    
    sortedRows.forEach(function(row) {
        tbody.appendChild(row);
    });
}

// ============ COPY TO CLIPBOARD ============

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(function() {
        showToast('Скопировано в буфер обмена');
    }).catch(function(err) {
        console.error('Failed to copy:', err);
    });
}

function showToast(message, duration = 3000) {
    let toast = document.getElementById('toast');
    
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #262626;
            color: white;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 0.9rem;
            z-index: 10000;
            opacity: 0;
            transition: opacity 0.3s;
        `;
        document.body.appendChild(toast);
    }
    
    toast.textContent = message;
    toast.style.opacity = '1';
    
    setTimeout(function() {
        toast.style.opacity = '0';
    }, duration);
}

// ============ KEYBOARD SHORTCUTS ============

document.addEventListener('keydown', function(event) {
    // Escape to close modals or alerts
    if (event.key === 'Escape') {
        const alerts = document.querySelectorAll('.alert');
        alerts.forEach(function(alert) {
            alert.remove();
        });
        
        const mobileMenu = document.querySelector('.navbar-menu.active');
        if (mobileMenu) {
            mobileMenu.classList.remove('active');
        }
    }
});

// ============ SCROLL TO TOP ============

function scrollToTop() {
    window.scrollTo({
        top: 0,
        behavior: 'smooth'
    });
}

// Show scroll-to-top button when scrolled down
document.addEventListener('DOMContentLoaded', function() {
    const scrollBtn = document.createElement('button');
    scrollBtn.id = 'scroll-top-btn';
    scrollBtn.innerHTML = '↑';
    scrollBtn.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        border: none;
        background: linear-gradient(45deg, #E1306C, #833AB4);
        color: white;
        font-size: 18px;
        cursor: pointer;
        opacity: 0;
        transition: opacity 0.3s;
        z-index: 1000;
        display: flex;
        align-items: center;
        justify-content: center;
    `;
    scrollBtn.onclick = scrollToTop;
    document.body.appendChild(scrollBtn);
    
    window.addEventListener('scroll', function() {
        if (window.scrollY > 300) {
            scrollBtn.style.opacity = '1';
        } else {
            scrollBtn.style.opacity = '0';
        }
    });
});

// ============ DARK MODE TOGGLE (Optional) ============

function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
}

// Check for saved dark mode preference
document.addEventListener('DOMContentLoaded', function() {
    if (localStorage.getItem('darkMode') === 'true') {
        document.body.classList.add('dark-mode');
    }
});

// ============ UTILITY FUNCTIONS ============

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    }
    if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Export functions for global use
window.toggleMobileMenu = toggleMobileMenu;
window.copyToClipboard = copyToClipboard;
window.showToast = showToast;
window.sortTable = sortTable;
window.scrollToTop = scrollToTop;
window.toggleDarkMode = toggleDarkMode;
window.formatNumber = formatNumber;
window.formatDate = formatDate;
