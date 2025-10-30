// Global state
let currentTab = 'dashboard';
let currentSort = 'plays';
let categoryChart = null;
let dayOfWeekChart = null;
let hourOfDayChart = null;
let discoveryChart = null;
let playDistributionChart = null;
let correlationChart = null;
let retentionChart = null;
let durationChart = null;
let sourceChart = null;
let currentHistoryPage = 1;
const historyPageSize = 50;
let currentExplorerPage = 1;
const explorerPageSize = 50;

// Cache implementation
const apiCache = new Map();
const CACHE_DURATION = 60000; // 1 minute

// Lazy chart rendering tracker
const renderedCharts = {
    dashboard: false,
    statistics: false,
    history: false,
    insights: false,
    analytics: false,
    explorer: false
};

// Chart instances for cleanup
const chartInstances = {
    category: null,
    dayOfWeek: null,
    hourOfDay: null,
    discovery: null,
    playDistribution: null,
    correlation: null,
    retention: null,
    duration: null,
    source: null
};

// Loading state functions
function showLoading(containerId) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `
            <div class="loading-skeleton">
                <div class="skeleton-item"></div>
                <div class="skeleton-item"></div>
                <div class="skeleton-item"></div>
            </div>
        `;
    }
}

function hideLoading(containerId) {
    const container = document.getElementById(containerId);
    if (container && container.querySelector('.loading-skeleton')) {
        container.innerHTML = '';
    }
}

function showError(message, containerId = null) {
    const content = `<div class="error-message">${message}</div>`;
    if (containerId) {
        const container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = content;
        }
    } else {
        console.error(message);
    }
}

function showEmpty(message, containerId) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `<div class="empty-state">${message}</div>`;
    }
}

// Error handling wrapper
async function fetchWithErrorHandling(endpoint, options = {}) {
    try {
        // Prepend BASE_PATH for Home Assistant ingress support
        const url = BASE_PATH + endpoint;
        const response = await fetch(url, options);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        if (!data.success) {
            throw new Error(data.error || 'Unknown error');
        }
        return data.data;
    } catch (error) {
        console.error('Fetch error:', error);
        showError(`Failed to load data: ${error.message}`);
        return null;
    }
}

// Caching wrapper
async function fetchWithCache(endpoint) {
    const cached = apiCache.get(endpoint);
    if (cached && Date.now() - cached.timestamp < CACHE_DURATION) {
        return cached.data;
    }

    const data = await fetchWithErrorHandling(endpoint);
    if (data) {
        apiCache.set(endpoint, { data, timestamp: Date.now() });
    }
    return data;
}

// Helper functions
async function fetchStats(endpoint) {
    return fetchWithCache(endpoint);
}

function formatTimeAgo(dateString) {
    if (!dateString) return 'Never';

    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;

    return date.toLocaleDateString();
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

function getRatingIcon(rating) {
    if (rating === 'like') return '👍';
    if (rating === 'dislike') return '👎';
    return '➖';
}

function formatDate(dateString) {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

function formatTime(dateTimeString) {
    if (!dateTimeString) return '';
    const date = new Date(dateTimeString);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function groupByDate(items, dateField) {
    const groups = {};
    items.forEach(item => {
        const date = item[dateField] ? item[dateField].split(' ')[0] : 'Unknown';
        if (!groups[date]) {
            groups[date] = [];
        }
        groups[date].push(item);
    });
    return groups;
}

// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const tabId = btn.dataset.tab;
        switchTab(tabId);
    });
});

function switchTab(tabId) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    // Show selected tab
    document.getElementById(tabId).classList.add('active');
    document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');

    currentTab = tabId;

    // Lazy loading: only load data when tab first becomes active
    if (!renderedCharts[tabId]) {
        loadTabData(tabId);
        renderedCharts[tabId] = true;
    }
}

async function loadTabData(tabId) {
    switch(tabId) {
        case 'dashboard':
            await loadDashboardData();
            break;
        case 'statistics':
            await loadStatisticsData();
            break;
        case 'history':
            await loadHistoryData();
            break;
        case 'insights':
            await loadInsightsData();
            break;
        case 'analytics':
            await loadAnalyticsData();
            break;
        case 'explorer':
            await loadExplorerData();
            break;
    }
}

// Dashboard Tab
async function loadDashboardData() {
    const [summary, recent, mostPlayed, channels, recommendations] = await Promise.all([
        fetchStats('/api/stats/summary'),
        fetchStats('/api/stats/recent?limit=10'),
        fetchStats('/api/stats/most-played?limit=5'),
        fetchStats('/api/stats/top-channels?limit=5'),
        fetchStats('/api/recommendations?strategy=likes&limit=10')
    ]);

    if (summary) {
        document.getElementById('total-videos').textContent = formatNumber(summary.total_videos);
        document.getElementById('total-plays').textContent = formatNumber(summary.total_plays);
        document.getElementById('total-likes').textContent = formatNumber(summary.liked);
        document.getElementById('avg-rating').textContent = summary.avg_rating_score.toFixed(1);
    }

    if (recent) {
        renderRecentActivity(recent);
    }

    if (mostPlayed) {
        renderMostPlayedMini(mostPlayed);
    }

    if (channels) {
        renderTopChannelsMini(channels);
    }

    if (recommendations) {
        renderRecommendations(recommendations);
    }
}

function renderRecentActivity(items) {
    const container = document.getElementById('recent-activity-list');
    if (!items || items.length === 0) {
        container.innerHTML = '<p style="color: #666; padding: 20px; text-align: center;">No recent activity</p>';
        return;
    }

    container.innerHTML = items.map(item => `
        <div class="activity-item">
            <div class="activity-title">${item.ha_title || item.yt_title || 'Unknown'}</div>
            <div class="activity-meta">
                ${item.ha_artist || item.yt_channel || 'Unknown'} •
                Played ${formatTimeAgo(item.date_last_played)} •
                ${getRatingIcon(item.rating)}
            </div>
        </div>
    `).join('');
}

function renderMostPlayedMini(items) {
    const container = document.getElementById('most-played-today');
    if (!items || items.length === 0) {
        container.innerHTML = '<p style="color: #666; padding: 10px;">No data</p>';
        return;
    }

    container.innerHTML = items.map((item, idx) => `
        <div class="activity-item">
            <div class="activity-title">#${idx + 1} ${item.ha_title || item.yt_title || 'Unknown'}</div>
            <div class="activity-meta">
                ${item.play_count} plays • ${getRatingIcon(item.rating)}
            </div>
        </div>
    `).join('');
}

function renderTopChannelsMini(items) {
    const container = document.getElementById('top-channels-mini');
    if (!items || items.length === 0) {
        container.innerHTML = '<p style="color: #666; padding: 10px;">No data</p>';
        return;
    }

    container.innerHTML = items.map((item, idx) => `
        <div class="activity-item">
            <div class="activity-title">#${idx + 1} ${item.yt_channel || 'Unknown'}</div>
            <div class="activity-meta">
                ${item.video_count} videos • ${item.total_plays} plays
            </div>
        </div>
    `).join('');
}

function renderRecommendations(items) {
    const container = document.getElementById('recommendations-list');
    if (!items || items.length === 0) {
        container.innerHTML = '<p style="color: #666; padding: 10px;">No recommendations available</p>';
        return;
    }

    container.innerHTML = items.map((item, idx) => `
        <div class="activity-item">
            <div class="activity-title">#${idx + 1} ${item.ha_title || item.yt_title || 'Unknown'}</div>
            <div class="activity-meta">
                ${item.ha_artist || item.yt_channel || 'Unknown'} • ${item.play_count} plays • ${getRatingIcon(item.rating)}
            </div>
        </div>
    `).join('');
}

// Statistics Tab
async function loadStatisticsData() {
    const [mostPlayed, topRated, channels, categories, summary] = await Promise.all([
        fetchStats('/api/stats/most-played?limit=20'),
        fetchStats('/api/stats/top-rated?limit=20'),
        fetchStats('/api/stats/top-channels?limit=10'),
        fetchStats('/api/stats/categories'),
        fetchStats('/api/stats/summary')
    ]);

    // Render video lists with sorting
    if (currentSort === 'plays' && mostPlayed) {
        renderVideoList(mostPlayed, 'plays');
    } else if (currentSort === 'rated' && topRated) {
        renderVideoList(topRated, 'rated');
    }

    // Setup toggle buttons
    setupToggleButtons(mostPlayed, topRated);

    // Render channel table
    if (channels) {
        renderChannelTable(channels);
    }

    // Render category chart
    if (categories) {
        renderCategoryChart(categories);
    }

    // Render rating distribution
    if (summary) {
        renderRatingDistribution(summary);
    }
}

function setupToggleButtons(mostPlayed, topRated) {
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const sortType = btn.dataset.sort;
            currentSort = sortType;

            if (sortType === 'plays' && mostPlayed) {
                renderVideoList(mostPlayed, 'plays');
            } else if (sortType === 'rated' && topRated) {
                renderVideoList(topRated, 'rated');
            }
        });
    });
}

function renderVideoList(videos, sortType) {
    const container = document.getElementById('top-videos-list');
    if (!videos || videos.length === 0) {
        container.innerHTML = '<p style="color: #666; padding: 20px; text-align: center;">No data</p>';
        return;
    }

    container.innerHTML = videos.map((video, idx) => `
        <div class="video-item">
            <div class="rank">#${idx + 1}</div>
            <div class="video-info">
                <div class="video-title">${video.ha_title || video.yt_title || 'Unknown'}</div>
                <div class="video-meta">
                    ${video.ha_artist || video.yt_channel || 'Unknown'}
                </div>
            </div>
            <div class="video-stats">
                ${sortType === 'plays'
                    ? `<span>▶️ ${video.play_count} plays</span>`
                    : `<span>⭐ ${video.rating_score} score</span>`
                }
                <span class="rating-badge ${video.rating}">
                    ${getRatingIcon(video.rating)}
                </span>
            </div>
        </div>
    `).join('');
}

function renderChannelTable(channels) {
    const container = document.getElementById('channel-stats-table');
    if (!channels || channels.length === 0) {
        container.innerHTML = '<p style="color: #666; padding: 20px; text-align: center;">No data</p>';
        return;
    }

    container.innerHTML = `
        <table class="stats-table">
            <thead>
                <tr>
                    <th>Channel</th>
                    <th>Videos</th>
                    <th>Total Plays</th>
                    <th>Avg Rating</th>
                </tr>
            </thead>
            <tbody>
                ${channels.map(ch => `
                    <tr>
                        <td>${ch.yt_channel || 'Unknown'}</td>
                        <td>${ch.video_count}</td>
                        <td>${ch.total_plays}</td>
                        <td>${ch.avg_rating !== null ? ch.avg_rating.toFixed(1) : '-'}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

function renderCategoryChart(categories) {
    const categoryNames = {
        1: 'Film & Animation',
        2: 'Autos & Vehicles',
        10: 'Music',
        15: 'Pets & Animals',
        17: 'Sports',
        18: 'Short Movies',
        19: 'Travel & Events',
        20: 'Gaming',
        21: 'Videoblogging',
        22: 'People & Blogs',
        23: 'Comedy',
        24: 'Entertainment',
        25: 'News & Politics',
        26: 'Howto & Style',
        27: 'Education',
        28: 'Science & Technology',
        29: 'Nonprofits & Activism'
    };

    if (!categories || categories.length === 0) {
        document.getElementById('category-chart-container').innerHTML =
            '<p style="color: #666; padding: 20px; text-align: center;">No category data</p>';
        return;
    }

    const ctx = document.getElementById('category-chart').getContext('2d');

    // Destroy existing chart if it exists
    if (categoryChart) {
        categoryChart.destroy();
    }

    categoryChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: categories.map(c => categoryNames[c.yt_category_id] || `Category ${c.yt_category_id}`),
            datasets: [{
                data: categories.map(c => c.count),
                backgroundColor: [
                    '#667eea', '#764ba2', '#f093fb', '#4facfe',
                    '#43e97b', '#fa709a', '#fee140', '#30cfd0',
                    '#a8edea', '#fed6e3', '#c471f5', '#12c2e9'
                ]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        font: {
                            size: 12
                        },
                        padding: 10
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((value / total) * 100).toFixed(1);
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

function renderRatingDistribution(summary) {
    const total = summary.liked + summary.disliked + summary.unrated;

    if (total === 0) {
        document.getElementById('count-likes').textContent = '0';
        document.getElementById('count-dislikes').textContent = '0';
        document.getElementById('count-none').textContent = '0';
        return;
    }

    const likePercent = (summary.liked / total) * 100;
    const dislikePercent = (summary.disliked / total) * 100;
    const nonePercent = (summary.unrated / total) * 100;

    document.getElementById('bar-likes').style.width = `${likePercent}%`;
    document.getElementById('bar-dislikes').style.width = `${dislikePercent}%`;
    document.getElementById('bar-none').style.width = `${nonePercent}%`;

    document.getElementById('count-likes').textContent = summary.liked;
    document.getElementById('count-dislikes').textContent = summary.disliked;
    document.getElementById('count-none').textContent = summary.unrated;
}

// History Tab
async function loadHistoryData() {
    const filters = {
        limit: historyPageSize,
        offset: (currentHistoryPage - 1) * historyPageSize,
        from: document.getElementById('date-from').value,
        to: document.getElementById('date-to').value
    };

    const params = new URLSearchParams();
    params.append('limit', filters.limit);
    params.append('offset', filters.offset);
    if (filters.from) params.append('from', filters.from);
    if (filters.to) params.append('to', filters.to);

    const history = await fetchStats(`/api/history/plays?${params}`);
    if (history) {
        renderHistoryTimeline(history);
        updatePaginationControls();
    }
}

function renderHistoryTimeline(items) {
    const container = document.getElementById('history-timeline');

    if (!items || items.length === 0) {
        container.innerHTML = '<p style="color: #666; padding: 20px; text-align: center;">No history found</p>';
        return;
    }

    const groupedByDate = groupByDate(items, 'date_last_played');

    container.innerHTML = Object.entries(groupedByDate).map(([date, videos]) => `
        <div class="history-date-group">
            <h3 class="date-header">${formatDate(date)}</h3>
            <div class="history-items">
                ${videos.map(video => `
                    <div class="history-item">
                        <div class="time">${formatTime(video.date_last_played)}</div>
                        <div class="video-info">
                            <div class="title">${video.ha_title || video.yt_title || 'Unknown'}</div>
                            <div class="meta">
                                ${video.ha_artist || video.yt_channel || 'Unknown'} •
                                ${video.play_count} plays •
                                ${getRatingIcon(video.rating)}
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

function updatePaginationControls() {
    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');
    const pageInfo = document.getElementById('page-info');

    prevBtn.disabled = currentHistoryPage === 1;
    pageInfo.textContent = `Page ${currentHistoryPage}`;
}

// Search functionality with debouncing
let searchTimeout;
document.getElementById('history-search').addEventListener('input', (e) => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(async () => {
        const query = e.target.value;
        if (query.length >= 2) {
            const results = await fetchStats(`/api/history/search?q=${encodeURIComponent(query)}`);
            if (results) {
                renderHistoryTimeline(results);
            }
        } else if (query.length === 0) {
            loadHistoryData();
        }
    }, 300);
});

// Pagination event listeners
document.getElementById('prev-page').addEventListener('click', () => {
    if (currentHistoryPage > 1) {
        currentHistoryPage--;
        loadHistoryData();
    }
});

document.getElementById('next-page').addEventListener('click', () => {
    currentHistoryPage++;
    loadHistoryData();
});

// Filter event listeners
document.getElementById('apply-filters').addEventListener('click', () => {
    currentHistoryPage = 1;
    loadHistoryData();
});

document.getElementById('clear-filters').addEventListener('click', () => {
    document.getElementById('date-from').value = '';
    document.getElementById('date-to').value = '';
    currentHistoryPage = 1;
    loadHistoryData();
});

// Insights Tab
async function loadInsightsData() {
    const [patterns, trends] = await Promise.all([
        fetchStats('/api/insights/patterns'),
        fetchStats('/api/insights/trends')
    ]);

    if (patterns) {
        renderDayOfWeekChart(patterns.by_day);
        renderHourOfDayChart(patterns.by_hour);
        updateInsightCards(patterns, trends);
    }

    if (trends) {
        renderDiscoveryChart(trends.discovery);
        renderPlayDistributionChart(trends.play_distribution);
    }
}

function renderDayOfWeekChart(data) {
    const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const ctx = document.getElementById('day-of-week-chart').getContext('2d');

    if (dayOfWeekChart) {
        dayOfWeekChart.destroy();
    }

    if (!data || data.length === 0) {
        return;
    }

    dayOfWeekChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(d => dayNames[d.day_of_week]),
            datasets: [{
                label: 'Plays',
                data: data.map(d => d.play_count),
                backgroundColor: '#36A2EB'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            scales: {
                y: {
                    beginAtZero: true
                }
            },
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });
}

function renderHourOfDayChart(data) {
    const ctx = document.getElementById('hour-of-day-chart').getContext('2d');

    if (hourOfDayChart) {
        hourOfDayChart.destroy();
    }

    if (!data || data.length === 0) {
        return;
    }

    hourOfDayChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.map(d => `${d.hour}:00`),
            datasets: [{
                label: 'Plays',
                data: data.map(d => d.play_count),
                borderColor: '#FF6384',
                backgroundColor: 'rgba(255, 99, 132, 0.1)',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            scales: {
                y: {
                    beginAtZero: true
                }
            },
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });
}

function renderDiscoveryChart(data) {
    const ctx = document.getElementById('discovery-chart').getContext('2d');

    if (discoveryChart) {
        discoveryChart.destroy();
    }

    if (!data || data.length === 0) {
        return;
    }

    discoveryChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.reverse().map(d => d.week),
            datasets: [{
                label: 'New Videos',
                data: data.map(d => d.new_videos),
                borderColor: '#4BC0C0',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            scales: {
                y: {
                    beginAtZero: true
                }
            },
            plugins: {
                legend: {
                    display: false
                },
                title: {
                    display: true,
                    text: 'New Videos Discovered Per Week (Last 12 Weeks)'
                }
            }
        }
    });
}

function renderPlayDistributionChart(data) {
    const ctx = document.getElementById('play-distribution-chart').getContext('2d');

    if (playDistributionChart) {
        playDistributionChart.destroy();
    }

    if (!data || data.length === 0) {
        return;
    }

    const order = ['1 play', '2-5 plays', '6-10 plays', '11-20 plays', '20+ plays'];
    const sortedData = order.map(range =>
        data.find(d => d.play_range === range) || { play_range: range, video_count: 0 }
    );

    playDistributionChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: sortedData.map(d => d.play_range),
            datasets: [{
                label: 'Number of Videos',
                data: sortedData.map(d => d.video_count),
                backgroundColor: '#9966FF'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            scales: {
                y: {
                    beginAtZero: true
                }
            },
            plugins: {
                legend: {
                    display: false
                },
                title: {
                    display: true,
                    text: 'Distribution of Videos by Play Count'
                }
            }
        }
    });
}

function updateInsightCards(patterns, trends) {
    if (!patterns.by_day || patterns.by_day.length === 0) {
        document.getElementById('most-active-day').textContent = 'N/A';
        document.getElementById('peak-hour').textContent = 'N/A';
        document.getElementById('discovery-rate').textContent = '0';
        return;
    }

    // Find most active day
    const mostActiveDay = patterns.by_day.reduce((max, day) =>
        day.play_count > max.play_count ? day : max
    );
    const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    document.getElementById('most-active-day').textContent = dayNames[mostActiveDay.day_of_week];

    // Find peak hour
    if (patterns.by_hour && patterns.by_hour.length > 0) {
        const peakHour = patterns.by_hour.reduce((max, hour) =>
            hour.play_count > max.play_count ? hour : max
        );
        document.getElementById('peak-hour').textContent = `${peakHour.hour}:00 - ${peakHour.hour + 1}:00`;
    } else {
        document.getElementById('peak-hour').textContent = 'N/A';
    }

    // Calculate discovery rate
    if (trends && trends.discovery && trends.discovery.length > 0) {
        const avgNewVideos = trends.discovery.reduce((sum, week) =>
            sum + week.new_videos, 0) / trends.discovery.length;
        document.getElementById('discovery-rate').textContent = avgNewVideos.toFixed(1);
    } else {
        document.getElementById('discovery-rate').textContent = '0';
    }
}

// Analytics Tab
async function loadAnalyticsData() {
    const [correlation, retention, duration, source] = await Promise.all([
        fetchStats('/api/analytics/correlation'),
        fetchStats('/api/analytics/retention'),
        fetchStats('/api/analytics/duration'),
        fetchStats('/api/analytics/source')
    ]);

    if (correlation) {
        renderCorrelationChart(correlation);
    }

    if (retention) {
        renderRetentionChart(retention);
    }

    if (duration) {
        renderDurationChart(duration);
    }

    if (source) {
        renderSourceChart(source);
    }
}

function renderCorrelationChart(data) {
    const ctx = document.getElementById('correlation-chart').getContext('2d');

    if (correlationChart) {
        correlationChart.destroy();
    }

    const likeData = data.like || { avg_play_count: 0, video_count: 0 };
    const dislikeData = data.dislike || { avg_play_count: 0, video_count: 0 };
    const noneData = data.none || { avg_play_count: 0, video_count: 0 };

    correlationChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['Liked', 'Disliked', 'No Rating'],
            datasets: [{
                label: 'Average Play Count',
                data: [
                    likeData.avg_play_count || 0,
                    dislikeData.avg_play_count || 0,
                    noneData.avg_play_count || 0
                ],
                backgroundColor: ['#4CAF50', '#f44336', '#9E9E9E']
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Average Plays'
                    }
                }
            },
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });

    // Add insight text
    const likedAvg = likeData.avg_play_count || 0;
    const noneAvg = noneData.avg_play_count || 0;
    let insight = '';

    if (likedAvg > 0 && noneAvg > 0 && likedAvg > noneAvg) {
        const percent = ((likedAvg / noneAvg - 1) * 100).toFixed(0);
        insight = `Liked videos are played ${percent}% more often on average.`;
    } else if (noneAvg > 0) {
        insight = 'No strong correlation between rating and play count.';
    } else {
        insight = 'Insufficient data for correlation analysis.';
    }

    document.getElementById('correlation-insight').textContent = insight;
}

function renderRetentionChart(data) {
    const ctx = document.getElementById('retention-chart').getContext('2d');

    if (retentionChart) {
        retentionChart.destroy();
    }

    if (!data || data.length === 0) {
        return;
    }

    retentionChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: data.map(d => d.retention_type),
            datasets: [{
                data: data.map(d => d.percentage),
                backgroundColor: ['#FF6384', '#36A2EB']
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const item = data[context.dataIndex];
                            return `${context.label}: ${context.parsed}% (${item.count} videos)`;
                        }
                    }
                }
            }
        }
    });
}

function renderDurationChart(data) {
    const ctx = document.getElementById('duration-chart').getContext('2d');

    if (durationChart) {
        durationChart.destroy();
    }

    if (!data || data.length === 0) {
        return;
    }

    const order = ['Under 3 min', '3-5 min', '5-10 min', 'Over 10 min'];
    const sortedData = order.map(bucket =>
        data.find(d => d.duration_bucket === bucket) || { duration_bucket: bucket, count: 0, avg_plays: 0, likes: 0 }
    );

    durationChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: sortedData.map(d => d.duration_bucket),
            datasets: [
                {
                    label: 'Video Count',
                    data: sortedData.map(d => d.count),
                    backgroundColor: '#36A2EB',
                    yAxisID: 'y'
                },
                {
                    label: 'Avg Plays',
                    data: sortedData.map(d => d.avg_plays),
                    backgroundColor: '#FF9F40',
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            scales: {
                y: {
                    type: 'linear',
                    position: 'left',
                    beginAtZero: true,
                    title: { display: true, text: 'Video Count' }
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    beginAtZero: true,
                    title: { display: true, text: 'Avg Plays' },
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
}

function renderSourceChart(data) {
    const ctx = document.getElementById('source-chart').getContext('2d');

    if (sourceChart) {
        sourceChart.destroy();
    }

    if (!data || data.length === 0) {
        return;
    }

    const sourceLabels = {
        'ha_live': 'Live Playback',
        'import_watch_history': 'Watch History Import',
        'import_liked_videos': 'Liked Videos Import'
    };

    sourceChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: data.map(d => sourceLabels[d.source] || d.source),
            datasets: [{
                data: data.map(d => d.count),
                backgroundColor: ['#667eea', '#764ba2', '#f093fb']
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom'
                }
            }
        }
    });
}

// Explorer Tab
async function loadExplorerData() {
    const [channels, categories] = await Promise.all([
        fetchStats('/api/explorer/channels'),
        fetchStats('/api/explorer/categories')
    ]);

    if (channels) {
        populateChannelFilter(channels);
    }

    if (categories) {
        populateCategoryFilter(categories);
    }

    // Load initial results
    await applyExplorerFilters();
}

function populateChannelFilter(channels) {
    const select = document.getElementById('filter-channel');
    select.innerHTML = '<option value="">All Channels</option>';

    channels.forEach(channel => {
        const option = document.createElement('option');
        option.value = channel.yt_channel_id;
        option.textContent = channel.yt_channel;
        select.appendChild(option);
    });
}

function populateCategoryFilter(categories) {
    const categoryNames = {
        1: 'Film & Animation',
        2: 'Autos & Vehicles',
        10: 'Music',
        15: 'Pets & Animals',
        17: 'Sports',
        18: 'Short Movies',
        19: 'Travel & Events',
        20: 'Gaming',
        21: 'Videoblogging',
        22: 'People & Blogs',
        23: 'Comedy',
        24: 'Entertainment',
        25: 'News & Politics',
        26: 'Howto & Style',
        27: 'Education',
        28: 'Science & Technology',
        29: 'Nonprofits & Activism'
    };

    const select = document.getElementById('filter-category');
    select.innerHTML = '<option value="">All Categories</option>';

    categories.forEach(catId => {
        const option = document.createElement('option');
        option.value = catId;
        option.textContent = categoryNames[catId] || `Category ${catId}`;
        select.appendChild(option);
    });
}

async function applyExplorerFilters() {
    const filters = getCurrentFilters();
    filters.limit = explorerPageSize;
    filters.offset = (currentExplorerPage - 1) * explorerPageSize;

    try {
        const response = await fetch(BASE_PATH + '/api/explorer/filter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(filters)
        });

        const result = await response.json();
        if (result.success) {
            renderExplorerResults(result.data);
        }
    } catch (error) {
        console.error('Error applying filters:', error);
    }
}

function getCurrentFilters() {
    const filters = {
        rating: document.getElementById('filter-rating').value,
        channel_id: document.getElementById('filter-channel').value,
        category: document.getElementById('filter-category').value,
        source: document.getElementById('filter-source').value,
        play_count_min: document.getElementById('filter-plays-min').value,
        play_count_max: document.getElementById('filter-plays-max').value,
        date_from: document.getElementById('filter-date-from').value,
        date_to: document.getElementById('filter-date-to').value,
        duration_min: document.getElementById('filter-duration-min').value,
        duration_max: document.getElementById('filter-duration-max').value,
        sort_by: document.getElementById('sort-by').value,
        sort_order: document.getElementById('sort-order').value
    };

    // Remove empty values
    Object.keys(filters).forEach(key => {
        if (!filters[key]) {
            delete filters[key];
        }
    });

    return filters;
}

function renderExplorerResults(results) {
    document.getElementById('result-count').textContent = results.total || 0;

    const container = document.getElementById('explorer-results-list');

    if (!results.videos || results.videos.length === 0) {
        container.innerHTML = '<p style="color: #666; padding: 20px; text-align: center;">No videos found</p>';
        return;
    }

    container.innerHTML = results.videos.map(video => `
        <div class="explorer-item">
            <div class="explorer-item-main">
                <div class="video-title">${video.ha_title || video.yt_title || 'Unknown'}</div>
                <div class="video-meta">
                    ${video.ha_artist || video.yt_channel || 'Unknown'} •
                    ${formatDuration(video.yt_duration || video.ha_duration)}
                </div>
            </div>
            <div class="explorer-item-stats">
                <span class="stat">▶️ ${video.play_count || 0}</span>
                <span class="stat">⭐ ${video.rating_score || 0}</span>
                <span class="rating-badge ${video.rating}">${getRatingIcon(video.rating)}</span>
            </div>
            <div class="explorer-item-dates">
                <span>Added: ${formatDate(video.date_added)}</span>
                ${video.date_last_played
                    ? `<span>Last played: ${formatTimeAgo(video.date_last_played)}</span>`
                    : '<span>Never played</span>'
                }
            </div>
        </div>
    `).join('');

    updateExplorerPagination(results.total);
}

function updateExplorerPagination(total) {
    const prevBtn = document.getElementById('explorer-prev-page');
    const nextBtn = document.getElementById('explorer-next-page');
    const pageInfo = document.getElementById('explorer-page-info');

    prevBtn.disabled = currentExplorerPage === 1;

    const totalPages = Math.ceil(total / explorerPageSize);
    nextBtn.disabled = currentExplorerPage >= totalPages;

    pageInfo.textContent = `Page ${currentExplorerPage} of ${totalPages}`;
}

function formatDuration(seconds) {
    if (!seconds) return 'Unknown';

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hours > 0) {
        return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    } else {
        return `${minutes}:${String(secs).padStart(2, '0')}`;
    }
}

// Export functionality
async function exportResults() {
    const filters = getCurrentFilters();
    filters.limit = 10000; // Get all results for export

    try {
        const response = await fetch(BASE_PATH + '/api/explorer/filter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(filters)
        });

        const result = await response.json();
        if (result.success && result.data.videos) {
            const csv = convertToCSV(result.data.videos);
            downloadCSV(csv, 'youtube-thumbs-export.csv');
        }
    } catch (error) {
        console.error('Error exporting results:', error);
    }
}

function convertToCSV(videos) {
    const headers = ['Title', 'Artist/Channel', 'Play Count', 'Rating', 'Rating Score', 'Date Added', 'Last Played', 'Duration'];
    const rows = videos.map(v => [
        v.ha_title || v.yt_title || '',
        v.ha_artist || v.yt_channel || '',
        v.play_count || 0,
        v.rating || '',
        v.rating_score || 0,
        v.date_added || '',
        v.date_last_played || '',
        v.yt_duration || v.ha_duration || ''
    ]);

    return [headers, ...rows].map(row =>
        row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')
    ).join('\n');
}

function downloadCSV(csv, filename) {
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
}

// Explorer event listeners
document.getElementById('apply-explorer-filters').addEventListener('click', () => {
    currentExplorerPage = 1;
    applyExplorerFilters();
});

document.getElementById('clear-explorer-filters').addEventListener('click', () => {
    document.querySelectorAll('.explorer-filters input, .explorer-filters select').forEach(el => {
        if (el.type === 'date' || el.type === 'number' || el.type === 'text') {
            el.value = '';
        } else if (el.tagName === 'SELECT') {
            el.selectedIndex = 0;
        }
    });
    currentExplorerPage = 1;
    applyExplorerFilters();
});

document.getElementById('export-results').addEventListener('click', exportResults);

document.getElementById('sort-by').addEventListener('change', applyExplorerFilters);
document.getElementById('sort-order').addEventListener('change', applyExplorerFilters);

document.getElementById('explorer-prev-page').addEventListener('click', () => {
    if (currentExplorerPage > 1) {
        currentExplorerPage--;
        applyExplorerFilters();
    }
});

document.getElementById('explorer-next-page').addEventListener('click', () => {
    currentExplorerPage++;
    applyExplorerFilters();
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey) {
        switch(e.key) {
            case '1':
                e.preventDefault();
                switchTab('dashboard');
                break;
            case '2':
                e.preventDefault();
                switchTab('statistics');
                break;
            case '3':
                e.preventDefault();
                switchTab('history');
                break;
            case '4':
                e.preventDefault();
                switchTab('insights');
                break;
            case '5':
                e.preventDefault();
                switchTab('analytics');
                break;
            case '6':
                e.preventDefault();
                switchTab('explorer');
                break;
            case 'r':
                e.preventDefault();
                refreshCurrentTab();
                break;
        }
    }
});

function refreshCurrentTab() {
    // Clear cache for current tab
    apiCache.clear();
    // Mark as not rendered to force reload
    renderedCharts[currentTab] = false;
    // Reload current tab data
    loadTabData(currentTab);
    renderedCharts[currentTab] = true;
}

// Dark mode functions
function toggleDarkMode() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);

    // Update toggle button icon
    const toggleBtn = document.getElementById('dark-mode-toggle');
    if (toggleBtn) {
        toggleBtn.textContent = newTheme === 'dark' ? '☀️' : '🌙';
    }

    // Update Chart.js theme
    updateChartTheme(newTheme);
}

function initializeTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    const toggleBtn = document.getElementById('dark-mode-toggle');
    if (toggleBtn) {
        toggleBtn.textContent = savedTheme === 'dark' ? '☀️' : '🌙';
    }
}

function updateChartTheme(theme) {
    Chart.defaults.color = theme === 'dark' ? '#e0e0e0' : '#666666';
    Chart.defaults.borderColor = theme === 'dark' ? '#404040' : '#e0e0e0';

    // Destroy all active charts
    if (categoryChart) categoryChart.destroy();
    if (dayOfWeekChart) dayOfWeekChart.destroy();
    if (hourOfDayChart) hourOfDayChart.destroy();
    if (discoveryChart) discoveryChart.destroy();
    if (playDistributionChart) playDistributionChart.destroy();
    if (correlationChart) correlationChart.destroy();
    if (retentionChart) retentionChart.destroy();
    if (durationChart) durationChart.destroy();
    if (sourceChart) sourceChart.destroy();

    // Reset chart instances
    categoryChart = null;
    dayOfWeekChart = null;
    hourOfDayChart = null;
    discoveryChart = null;
    playDistributionChart = null;
    correlationChart = null;
    retentionChart = null;
    durationChart = null;
    sourceChart = null;

    // Mark current tab as not rendered to force reload
    renderedCharts[currentTab] = false;

    // Reload current tab to recreate charts
    loadTabData(currentTab);
    renderedCharts[currentTab] = true;
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initializeTheme();
    loadTabData('dashboard');

    // Add dark mode toggle event listener
    const toggleBtn = document.getElementById('dark-mode-toggle');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', toggleDarkMode);
    }
});
