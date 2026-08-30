/**
 * Sentinel — Map Dashboard (static/js/map.js)
 *
 * Leaflet map centered on Gujarat, markers from /api/v1/cameras,
 * clustered via Leaflet.markercluster.
 *
 * Department layer-toggle + district dropdown → re-fetch + redraw.
 * Uses plain fetch(), NOT HTMX (see implementation plan Phase 4 note).
 */

function mapDashboard() {
    return {
        map: null,
        clusterGroup: null,
        allCameras: [],
        departments: [],
        districts: [],
        selectedDistrict: '',
        activeDepartments: new Set(),

        async init() {
            // Initialise Leaflet map centered on Gujarat
            this.map = L.map('map', {
                zoomControl: true,
                attributionControl: true,
            }).setView([22.3, 72.0], 7);

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
                maxZoom: 19,
            }).addTo(this.map);

            // Create cluster group
            this.clusterGroup = L.markerClusterGroup({
                showCoverageOnHover: false,
                maxClusterRadius: 50,
                spiderfyOnMaxZoom: true,
                disableClusteringAtZoom: 16,
            });
            this.map.addLayer(this.clusterGroup);

            // Load departments and districts for controls
            await Promise.all([
                this.loadDepartments(),
                this.loadDistricts(),
            ]);

            // Load cameras and render
            await this.loadAndRender();
        },

        async loadDepartments() {
            try {
                const res = await fetch('/api/v1/departments');
                this.departments = await res.json();

                // Build department checkboxes
                const container = document.getElementById('department-checkboxes');
                container.innerHTML = '';

                this.departments.forEach(dept => {
                    this.activeDepartments.add(dept.id);

                    const label = document.createElement('label');
                    label.className = 'checkbox-item';

                    const cb = document.createElement('input');
                    cb.type = 'checkbox';
                    cb.checked = true;
                    cb.value = dept.id;
                    cb.addEventListener('change', () => {
                        if (cb.checked) {
                            this.activeDepartments.add(dept.id);
                        } else {
                            this.activeDepartments.delete(dept.id);
                        }
                        this.renderMarkers();
                    });

                    const span = document.createElement('span');
                    span.textContent = dept.name;

                    label.appendChild(cb);
                    label.appendChild(span);
                    container.appendChild(label);
                });

                // Add "No Department" toggle for cameras without department_id
                const noDeptLabel = document.createElement('label');
                noDeptLabel.className = 'checkbox-item';
                const noDeptCb = document.createElement('input');
                noDeptCb.type = 'checkbox';
                noDeptCb.checked = true;
                noDeptCb.value = '__none__';
                this.activeDepartments.add('__none__');
                noDeptCb.addEventListener('change', () => {
                    if (noDeptCb.checked) {
                        this.activeDepartments.add('__none__');
                    } else {
                        this.activeDepartments.delete('__none__');
                    }
                    this.renderMarkers();
                });
                const noDeptSpan = document.createElement('span');
                noDeptSpan.textContent = 'Unassigned';
                noDeptLabel.appendChild(noDeptCb);
                noDeptLabel.appendChild(noDeptSpan);
                container.appendChild(noDeptLabel);

            } catch (e) {
                console.error('Failed to load departments:', e);
            }
        },

        async loadDistricts() {
            try {
                const res = await fetch('/api/v1/districts');
                this.districts = await res.json();

                const select = document.getElementById('district-filter');
                // Keep the "All Districts" option
                this.districts.forEach(d => {
                    const opt = document.createElement('option');
                    opt.value = d.id;
                    opt.textContent = d.name;
                    select.appendChild(opt);
                });
            } catch (e) {
                console.error('Failed to load districts:', e);
            }
        },

        async loadAndRender() {
            try {
                let url = '/api/v1/cameras';
                const params = new URLSearchParams();
                if (this.selectedDistrict) {
                    params.set('district_id', this.selectedDistrict);
                }
                if (params.toString()) {
                    url += '?' + params.toString();
                }
                const res = await fetch(url);
                this.allCameras = await res.json();
                this.renderMarkers();
            } catch (e) {
                console.error('Failed to load cameras:', e);
            }
        },

        filterByDistrict(districtId) {
            this.selectedDistrict = districtId;
            this.loadAndRender();
        },

        renderMarkers() {
            this.clusterGroup.clearLayers();

            let online = 0, offline = 0, maintenance = 0, total = 0;

            const statusEmoji = {
                'online': '🟢',
                'offline': '🔴',
                'maintenance': '🟡',
            };

            this.allCameras.forEach(cam => {
                // Skip cameras without location
                if (!cam.location) return;

                // Department filter
                const deptId = cam.department_id || '__none__';
                if (!this.activeDepartments.has(deptId)) return;

                total++;
                if (cam.connectivity_status === 'online') online++;
                else if (cam.connectivity_status === 'offline') offline++;
                else maintenance++;

                const [lon, lat] = cam.location.coordinates;
                const emoji = statusEmoji[cam.connectivity_status] || '⚪';

                const icon = L.divIcon({
                    html: `<span style="font-size: 1.4rem; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5));">${emoji}</span>`,
                    className: 'sentinel-marker',
                    iconSize: [28, 28],
                    iconAnchor: [14, 14],
                    popupAnchor: [0, -14],
                });

                const marker = L.marker([lat, lon], { icon });

                // Build popup
                let popupHtml = `
                    <div class="popup-content">
                        <div class="popup-title">${emoji} ${cam.name}</div>
                        <div class="popup-row">
                            <span class="popup-label">Department</span>
                            <span class="popup-value">${cam.department_name || '—'}</span>
                        </div>
                        <div class="popup-row">
                            <span class="popup-label">District</span>
                            <span class="popup-value">${cam.district_name || '—'}</span>
                        </div>
                        <div class="popup-row">
                            <span class="popup-label">Type</span>
                            <span class="popup-value">${cam.camera_type || '—'}</span>
                        </div>
                        <div class="popup-row">
                            <span class="popup-label">Ownership</span>
                            <span class="popup-value">${cam.ownership || '—'}</span>
                        </div>
                        <div class="popup-row">
                            <span class="popup-label">Status</span>
                            <span class="popup-value">
                                <span class="badge badge--${cam.connectivity_status}">
                                    <span class="badge-dot badge-dot--${cam.connectivity_status}"></span>
                                    ${cam.connectivity_status}
                                </span>
                            </span>
                        </div>
                        <div class="popup-row">
                            <span class="popup-label">Storage</span>
                            <span class="popup-value">${cam.storage_type || '—'}${cam.retention_days ? ' · ' + cam.retention_days + 'd' : ''}</span>
                        </div>`;

                if (cam.vms_url) {
                    popupHtml += `
                        <a href="${cam.vms_url}" target="_blank" rel="noopener" class="popup-link">
                            🖥️ Open VMS Viewer
                        </a>`;
                }

                popupHtml += `</div>`;

                marker.bindPopup(popupHtml, { maxWidth: 300, minWidth: 240 });
                this.clusterGroup.addLayer(marker);
            });

            // Update stats
            document.getElementById('stat-online').textContent = online;
            document.getElementById('stat-offline').textContent = offline;
            document.getElementById('stat-maintenance').textContent = maintenance;
            document.getElementById('stat-total').textContent = total;
        },
    };
}
