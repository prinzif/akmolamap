// frontend/assets/header.js
function injectHeader() {
    const headerHTML = `
    <header class="header">
        <div class="header-content">
            <div class="logo-section">
                <a href="/" class="logo" style="text-decoration:none;color:white;">
                    <span class="logo-icon">🛰️</span>
                    <div>
                        <div>AgroSentinel</div>
                        <div class="logo-subtitle">Акмолинская область</div>
                    </div>
                </a>
            </div>
            
            <nav class="nav-menu">
                <div class="nav-item">
                    <a href="/" class="nav-link ${location.pathname === '/' ? 'active' : ''}">
                        <span>🗺️ Главная</span>
                    </a>
                </div>
                
                <div class="nav-item">
                    <div class="nav-link">
                        <span>🌱 Индексы ▼</span>
                    </div>
                    <div class="dropdown-menu">
                        <a href="/ndvi" class="dropdown-item">📊 NDVI</a>
                        <a href="/biopar" class="dropdown-item">🌿 BIOPAR</a>
                    </div>
                </div>
            </nav>
        </div>
    </header>`;
    
    document.body.insertAdjacentHTML('afterbegin', headerHTML);
}

// Вызов при загрузке
document.addEventListener('DOMContentLoaded', injectHeader);