/**
 * Consistent Table Enhancement Utility
 * Provides sorting, resizing, column toggle, and persistence features for tables
 */
class ConsistentTable {
    constructor(tableElement, config = {}) {
        this.table = tableElement;
        this.config = {
            storageKey: config.storageKey || 'table-settings',
            enableSorting: config.enableSorting !== false,
            enableResizing: config.enableResizing !== false,
            enableColumnToggle: config.enableColumnToggle !== false,
            ...config
        };
        
        this.settings = this.loadSettings();
        this.init();
    }

    init() {
        if (!this.table) return;

        this.setupTableStructure();
        
        if (this.config.enableSorting) {
            this.initSorting();
        }
        
        if (this.config.enableResizing) {
            this.initResizing();
        }
        
        if (this.config.enableColumnToggle) {
            this.initColumnToggle();
        }
        
        this.applySettings();
        this.attachEventListeners();
    }

    setupTableStructure() {
        // Ensure table has proper class
        this.table.classList.add('enhanced-table');
        
        // Get headers
        this.headers = Array.from(this.table.querySelectorAll('thead th'));
        
        // Initialize column data
        this.columns = this.headers.map((header, index) => ({
            index,
            key: header.dataset.column || `col-${index}`,
            label: header.textContent.trim(),
            visible: true,
            sortable: header.dataset.sortable !== 'false',
            resizable: header.dataset.resizable !== 'false',
            width: null
        }));
    }

    initSorting() {
        this.sortState = { column: null, direction: 'asc' };

        // Check if we're using server-side sorting (based on URL params)
        const urlParams = new URLSearchParams(window.location.search);
        const sortBy = urlParams.get('sort_by');
        const sortDir = urlParams.get('sort_dir') || 'asc';

        this.headers.forEach((header, index) => {
            const column = this.columns[index];
            if (!column.sortable) return;

            header.style.cursor = 'pointer';
            header.classList.add('sortable');

            // Add sort indicator
            const indicator = document.createElement('span');
            indicator.className = 'sort-indicator';
            indicator.innerHTML = '↕';
            header.appendChild(indicator);

            // Use server-side sorting via URL navigation
            header.addEventListener('click', () => this.sortTableServerSide(column.key, index));

            // Update indicator if this is the current sort column
            if (sortBy === column.key) {
                indicator.innerHTML = sortDir === 'asc' ? '↑' : '↓';
                indicator.style.color = '#0066cc';
            }
        });
    }

    initResizing() {
        this.headers.forEach((header, index) => {
            const column = this.columns[index];
            if (!column.resizable) return;

            const resizer = document.createElement('div');
            resizer.className = 'column-resizer';
            resizer.style.cssText = `
                position: absolute;
                right: 0;
                top: 0;
                bottom: 0;
                width: 4px;
                cursor: col-resize;
                background: transparent;
            `;
            
            header.style.position = 'relative';
            header.appendChild(resizer);
            
            this.attachResizerEvents(resizer, index);
        });
    }

    initColumnToggle() {
        // Create column toggle dropdown
        const toggleButton = document.createElement('button');
        toggleButton.className = 'column-toggle-btn';
        toggleButton.type = 'button';
        toggleButton.innerHTML = '⚙ Columns';
        toggleButton.style.cssText = `
            margin-bottom: 10px;
            padding: 5px 10px;
            border: 1px solid #ddd;
            background: white;
            cursor: pointer;
            border-radius: 4px;
        `;
        
        const dropdown = document.createElement('div');
        dropdown.className = 'column-dropdown';
        dropdown.style.cssText = `
            display: none;
            position: absolute;
            background: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            z-index: 1000;
            padding: 10px;
            min-width: 150px;
        `;
        
        this.columns.forEach((column, index) => {
            const label = document.createElement('label');
            label.style.cssText = `
                display: block;
                margin: 5px 0;
                cursor: pointer;
            `;
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = column.visible;
            checkbox.style.marginRight = '5px';
            checkbox.addEventListener('change', () => this.toggleColumn(index, checkbox.checked));
            
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(column.label));
            dropdown.appendChild(label);
        });
        
        toggleButton.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
        });
        
        // Close dropdown when clicking outside
        document.addEventListener('click', () => {
            dropdown.style.display = 'none';
        });
        
        // Insert before table
        this.table.parentNode.insertBefore(toggleButton, this.table);
        this.table.parentNode.insertBefore(dropdown, this.table);
    }

    sortTableServerSide(columnKey, columnIndex) {
        // Get current URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        const currentSortBy = urlParams.get('sort_by');
        const currentSortDir = urlParams.get('sort_dir') || 'asc';

        // Determine new sort direction
        let newDirection = 'asc';
        if (currentSortBy === columnKey && currentSortDir === 'asc') {
            newDirection = 'desc';
        }

        // Update URL parameters
        urlParams.set('sort_by', columnKey);
        urlParams.set('sort_dir', newDirection);

        // Navigate to new URL with sort parameters
        window.location.search = urlParams.toString();
    }

    sortTable(columnIndex) {
        // Keep client-side sorting as fallback for legacy pages
        const column = this.columns[columnIndex];
        const tbody = this.table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));

        // Determine sort direction
        let direction = 'asc';
        if (this.sortState.column === columnIndex && this.sortState.direction === 'asc') {
            direction = 'desc';
        }

        // Sort rows
        rows.sort((a, b) => {
            const aText = a.children[columnIndex]?.textContent.trim() || '';
            const bText = b.children[columnIndex]?.textContent.trim() || '';

            // Try numeric comparison first
            const aNum = parseFloat(aText.replace(/[^\d.-]/g, ''));
            const bNum = parseFloat(bText.replace(/[^\d.-]/g, ''));

            let comparison = 0;
            if (!isNaN(aNum) && !isNaN(bNum)) {
                comparison = aNum - bNum;
            } else {
                comparison = aText.localeCompare(bText);
            }

            return direction === 'asc' ? comparison : -comparison;
        });

        // Update DOM
        rows.forEach(row => tbody.appendChild(row));

        // Update sort indicators
        this.updateSortIndicators(columnIndex, direction);

        // Save sort state
        this.sortState = { column: columnIndex, direction };
        this.saveSettings();
    }

    updateSortIndicators(activeColumn, direction) {
        this.headers.forEach((header, index) => {
            const indicator = header.querySelector('.sort-indicator');
            if (!indicator) return;
            
            if (index === activeColumn) {
                indicator.innerHTML = direction === 'asc' ? '↑' : '↓';
                indicator.style.color = '#0066cc';
            } else {
                indicator.innerHTML = '↕';
                indicator.style.color = '#ccc';
            }
        });
    }

    attachResizerEvents(resizer, columnIndex) {
        let isResizing = false;
        let startX = 0;
        let startWidth = 0;
        
        resizer.addEventListener('mousedown', (e) => {
            isResizing = true;
            startX = e.clientX;
            startWidth = this.headers[columnIndex].offsetWidth;
            
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
            
            e.preventDefault();
        });
        
        const handleMouseMove = (e) => {
            if (!isResizing) return;
            
            const width = startWidth + (e.clientX - startX);
            const minWidth = 50;
            
            if (width >= minWidth) {
                this.headers[columnIndex].style.width = width + 'px';
                this.columns[columnIndex].width = width;
            }
        };
        
        const handleMouseUp = () => {
            isResizing = false;
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            this.saveSettings();
        };
    }

    toggleColumn(columnIndex, visible) {
        this.columns[columnIndex].visible = visible;
        
        // Toggle header
        this.headers[columnIndex].style.display = visible ? '' : 'none';
        
        // Toggle cells
        const rows = this.table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            const cell = row.children[columnIndex];
            if (cell) {
                cell.style.display = visible ? '' : 'none';
            }
        });
        
        this.saveSettings();
    }

    applySettings() {
        // Apply column widths
        this.columns.forEach((column, index) => {
            if (column.width) {
                this.headers[index].style.width = column.width + 'px';
            }
            
            // Apply visibility
            this.toggleColumn(index, column.visible);
        });
        
        // Apply sort state
        if (this.sortState.column !== null) {
            this.sortTable(this.sortState.column);
        }
    }

    loadSettings() {
        try {
            const saved = localStorage.getItem(this.config.storageKey);
            return saved ? JSON.parse(saved) : {};
        } catch (e) {
            console.warn('Failed to load table settings:', e);
            return {};
        }
    }

    saveSettings() {
        try {
            const settings = {
                columns: this.columns.map(col => ({
                    key: col.key,
                    width: col.width,
                    visible: col.visible
                })),
                sortState: this.sortState
            };
            
            localStorage.setItem(this.config.storageKey, JSON.stringify(settings));
        } catch (e) {
            console.warn('Failed to save table settings:', e);
        }
    }

    attachEventListeners() {
        // Listen for window resize to adjust table
        window.addEventListener('resize', () => {
            // Recalculate table layout if needed
            this.table.style.tableLayout = 'fixed';
        });
    }
}

// Default modal content formatter
function formatModalContent(data) {
    if (typeof data === 'string') {
        return `<pre style="white-space: pre-wrap; font-family: monospace; background: #f5f5f5; padding: 15px; border-radius: 4px;">${data}</pre>`;
    }
    
    if (typeof data === 'object') {
        return `<pre style="white-space: pre-wrap; font-family: monospace; background: #f5f5f5; padding: 15px; border-radius: 4px;">${JSON.stringify(data, null, 2)}</pre>`;
    }
    
    return `<p>${data}</p>`;
}

// Export for module systems if available
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ConsistentTable, formatModalContent };
}