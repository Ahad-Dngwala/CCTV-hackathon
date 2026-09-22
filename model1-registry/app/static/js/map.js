/**
 * EyesOnGuj — Map Dashboard (static/js/map.js)
 *
 * Tactical GIS Command Dashboard centered on Gujarat.
 * Leaflet map, PostGIS boundary rendering, marker clustering via Leaflet.markercluster,
 * Slide-Over Telemetry Inspector Drawer, animated radar wave status markers,
 * and high-contrast tactical tile viewports.
 *
 * Uses plain fetch(), NOT HTMX. Preserves all GIS GeoJSON and XSS protections.
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
        gapOverlayLayer: null,
        showGapOverlay: false,
        districtBoundaryLayer: null,
        showDistrictBoundaries: true,

        // Tactical HUD & Telemetry Inspector State
        darkTiles: false,
        inspectorOpen: false,
        selectedCamera: null,
        selectedCameraStreamUrl: '',
        selectedCameraStreamLabel: 'Launch Live Stream View',
        currentTime: '',
        timeTimer: null,

        async init() {
            // Default dark tiles mode to match active theme
            const currentTheme = document.documentElement.getAttribute('data-theme');
            this.darkTiles = currentTheme !== 'light';

            // Clock ticker for tactical HUD
            const updateClock = () => {
                const now = new Date();
                this.currentTime = now.toLocaleTimeString('en-GB', { timeZone: 'Asia/Kolkata', hour12: false }) + ' IST';
            };
            updateClock();
            this.timeTimer = setInterval(updateClock, 1000);

            // Global bridge for popup buttons to open inspector
            window.eyesongujOpenInspector = (camId) => {
                const cam = this.allCameras.find(c => String(c.id) === String(camId));
                if (cam) {
                    this.openInspector(cam);
                }
            };

            // Check if map container is already initialized (hot-reload / Alpine safety)
            const mapContainer = document.getElementById('map');
            if (mapContainer && mapContainer._leaflet_id) {
                mapContainer._leaflet_id = null;
            }

            // Initialise Leaflet map centered on Gujarat [22.3, 72.0]
            this.map = L.map('map', {
                zoomControl: true,
                attributionControl: true,
                dragging: true,
                tap: false,
            }).setView([22.3, 72.0], 7);

            // Prevent clicks/drags on HUD floating panels from propagating to the Leaflet canvas
            setTimeout(() => {
                document.querySelectorAll('.map-control-card, .map-stats, .camera-inspector-drawer').forEach(el => {
                    L.DomEvent.disableClickPropagation(el);
                    L.DomEvent.disableScrollPropagation(el);
                });
            }, 100);

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
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

            // Draw real PostGIS district boundary polygons
            this.renderDistrictBoundaries();

            // Load cameras and render markers
            await this.loadAndRender();
        },

        openInspector(cam) {
            this.selectedCamera = cam;
            this.selectedCameraStreamUrl = '';
            this.selectedCameraStreamLabel = 'Launch Live Stream View';

            if (cam.vms_url) {
                this.selectedCameraStreamUrl = cam.vms_url;
                this.selectedCameraStreamLabel = 'Open VMS Viewer';
            } else if (cam.hls_url) {
                this.selectedCameraStreamUrl = cam.hls_url;
                this.selectedCameraStreamLabel = 'Open HLS Stream';
            } else if (cam.rtsp_url) {
                this.selectedCameraStreamUrl = `/api/v1/cameras/${cam.id}/live`;
                this.selectedCameraStreamLabel = 'Open Live MJPEG View';
            }

            this.inspectorOpen = true;
        },

        closeInspector() {
            this.inspectorOpen = false;
        },

        resetMapView() {
            if (this.map) {
                this.map.setView([22.3, 72.0], 7);
            }
        },

        toggleDarkTiles() {
            this.darkTiles = !this.darkTiles;
        },

        copyCoords() {
            if (this.selectedCamera && this.selectedCamera.location && this.selectedCamera.location.coordinates) {
                const [lon, lat] = this.selectedCamera.location.coordinates;
                const coordStr = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
                navigator.clipboard.writeText(coordStr);
            }
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
                this.districts.forEach(d => {
                    const opt = document.createElement('option');
                    opt.value = d.id;
                    opt.textContent = `${d.name} (${d.camera_count || 0} nodes)`;
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
            document.getElementById('district-filter').value = districtId;
        },

        renderDistrictBoundaries() {
            if (this.districtBoundaryLayer) {
                this.map.removeLayer(this.districtBoundaryLayer);
                this.districtBoundaryLayer = null;
            }

            const featureCollection = {
                type: 'FeatureCollection',
                features: this.districts
                    .filter(d => d.boundary)
                    .map(d => ({
                        type: 'Feature',
                        properties: { id: d.id, name: d.name, camera_count: d.camera_count },
                        geometry: d.boundary,
                    })),
            };

            if (featureCollection.features.length === 0) return;

            // Holographic cyber styling for district boundaries
            const baseStyle = { 
                color: '#00e5ff', 
                weight: 1.5, 
                opacity: 0.65, 
                fillOpacity: 0.04, 
                fillColor: '#00e5ff',
                dashArray: '3, 4'
            };
            const hoverStyle = { 
                color: '#38bdf8', 
                weight: 2.5, 
                opacity: 0.95, 
                fillOpacity: 0.16, 
                fillColor: '#00e5ff',
                dashArray: ''
            };

            this.districtBoundaryLayer = L.geoJSON(featureCollection, {
                style: () => ({ ...baseStyle }),
                onEachFeature: (feature, layer) => {
                    layer.bindTooltip(
                        `<div class="district-tooltip-content">
                            <strong>${feature.properties.name}</strong>
                            <span class="badge badge--sm badge--info" style="margin-left: 0.35rem;">${feature.properties.camera_count || 0} nodes</span>
                         </div>`, 
                        { sticky: true, className: 'district-tooltip', html: true }
                    );
                    layer.on('mouseover', () => layer.setStyle(hoverStyle));
                    layer.on('mouseout', () => layer.setStyle(baseStyle));
                    layer.on('click', () => this.filterByDistrict(feature.properties.id));
                },
            });

            if (this.showDistrictBoundaries) {
                this.districtBoundaryLayer.addTo(this.map);
                this.districtBoundaryLayer.bringToBack();
            }
        },

        toggleDistrictBoundaries(enable) {
            this.showDistrictBoundaries = enable;
            if (!this.districtBoundaryLayer) return;
            if (enable) {
                this.districtBoundaryLayer.addTo(this.map);
                this.districtBoundaryLayer.bringToBack();
            } else {
                this.map.removeLayer(this.districtBoundaryLayer);
            }
        },

        renderMarkers() {
            this.clusterGroup.clearLayers();

            let online = 0, offline = 0, maintenance = 0, total = 0;

            // High-tech status pins with animated radar pulse wave on online cameras
            const statusPins = {
                'online': `<svg class="map-camera-pin map-pin--online" width="34" height="42" viewBox="0 0 34 42" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="17" cy="15" r="14" fill="#00ff88" fill-opacity="0.25" class="radar-pulse-ring"/>
                    <path d="M17 2C9.82 2 4 7.82 4 15c0 9.5 13 22 13 22s13-12.5 13-22c0-7.18-5.82-13-13-13z" fill="#070d1a" stroke="#00ff88" stroke-width="2"/>
                    <circle cx="17" cy="15" r="6" fill="#00ff88" fill-opacity="0.3"/>
                    <circle cx="17" cy="15" r="3" fill="#00ff88"/>
                </svg>`,
                'offline': `<svg class="map-camera-pin map-pin--offline" width="34" height="42" viewBox="0 0 34 42" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M17 2C9.82 2 4 7.82 4 15c0 9.5 13 22 13 22s13-12.5 13-22c0-7.18-5.82-13-13-13z" fill="#070d1a" stroke="#ff3366" stroke-width="2"/>
                    <circle cx="17" cy="15" r="6" fill="#ff3366" fill-opacity="0.2"/>
                    <line x1="13.5" y1="11.5" x2="20.5" y2="18.5" stroke="#ff3366" stroke-width="2" stroke-linecap="round"/>
                    <line x1="20.5" y1="11.5" x2="13.5" y2="18.5" stroke="#ff3366" stroke-width="2" stroke-linecap="round"/>
                </svg>`,
                'maintenance': `<svg class="map-camera-pin map-pin--maintenance" width="34" height="42" viewBox="0 0 34 42" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M17 2C9.82 2 4 7.82 4 15c0 9.5 13 22 13 22s13-12.5 13-22c0-7.18-5.82-13-13-13z" fill="#070d1a" stroke="#ffaa00" stroke-width="2"/>
                    <circle cx="17" cy="15" r="6" fill="#ffaa00" fill-opacity="0.2"/>
                    <line x1="17" y1="10.5" x2="17" y2="15.5" stroke="#ffaa00" stroke-width="2" stroke-linecap="round"/>
                    <circle cx="17" cy="18.5" r="1" fill="#ffaa00"/>
                </svg>`
            };

            this.allCameras.forEach(cam => {
                if (!cam.location || !cam.location.coordinates) return;

                // Department filter
                const deptId = cam.department_id || '__none__';
                if (!this.activeDepartments.has(deptId)) return;

                total++;
                const status = (cam.connectivity_status || '').toLowerCase();
                if (status === 'online') online++;
                else if (status === 'offline') offline++;
                else if (status === 'maintenance') maintenance++;
                else offline++;

                const [lon, lat] = cam.location.coordinates;
                const pinSvg = statusPins[status] || statusPins['offline'];

                const icon = L.divIcon({
                    html: pinSvg,
                    className: 'eyesonguj-marker',
                    iconSize: [34, 42],
                    iconAnchor: [17, 39],
                    popupAnchor: [0, -36],
                });

                const marker = L.marker([lat, lon], { icon });

                // Wire pin click directly to the Slide-Over Inspector Drawer
                marker.on('click', () => {
                    this.openInspector(cam);
                });

                const escapeHtml = (unsafe) => {
                    return (unsafe || "").toString()
                         .replace(/&/g, "&amp;")
                         .replace(/</g, "&lt;")
                         .replace(/>/g, "&gt;")
                         .replace(/"/g, "&quot;")
                         .replace(/'/g, "&#039;");
                };

                const statusClass = ['online', 'offline', 'maintenance'].includes(status)
                    ? status
                    : 'unknown';

                let streamUrl = null;
                let streamLabel = "Open VMS Viewer";
                if (cam.vms_url) {
                    streamUrl = cam.vms_url;
                } else if (cam.hls_url) {
                    streamUrl = cam.hls_url;
                } else if (cam.rtsp_url) {
                    streamUrl = `/api/v1/cameras/${cam.id}/live`;
                    streamLabel = "Open Live View";
                }

                // Rich Pop-up Card
                let popupHtml = `
                    <div class="popup-content hud-bracket">
                        <div class="popup-title">
                            <span class="badge-dot badge-dot--${statusClass}"></span>
                            <span class="popup-name">${escapeHtml(cam.name)}</span>
                        </div>
                        <div class="popup-details">
                            <div class="popup-row">
                                <span class="popup-label">Department</span>
                                <span class="popup-value">${escapeHtml(cam.department_name || '—')}</span>
                            </div>
                            <div class="popup-row">
                                <span class="popup-label">District</span>
                                <span class="popup-value">${escapeHtml(cam.district_name || '—')}</span>
                            </div>
                            <div class="popup-row">
                                <span class="popup-label">Type</span>
                                <span class="popup-value">${escapeHtml(cam.camera_type || '—')}</span>
                            </div>
                            <div class="popup-row">
                                <span class="popup-label">Status</span>
                                <span class="popup-value">
                                    <span class="badge badge--${statusClass}">
                                        <span class="badge-dot badge-dot--${statusClass}"></span>
                                        ${statusClass.toUpperCase()}
                                    </span>
                                </span>
                            </div>
                        </div>
                        <div class="popup-action">
                            <button type="button" class="btn btn--secondary btn--sm btn--block popup-inspect-btn" onclick="window.eyesongujOpenInspector('${escapeHtml(cam.id)}')">
                                <svg class="svg-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>
                                <span>Inspect Telemetry</span>
                            </button>
                            ${streamUrl ? `
                            <a href="${escapeHtml(streamUrl)}" target="_blank" rel="noopener" class="popup-link btn btn--primary btn--sm btn--block" style="margin-top: 0.4rem;">
                                <svg class="svg-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                                <span>${streamLabel}</span>
                            </a>` : ''}
                        </div>
                    </div>`;

                marker.bindPopup(popupHtml, { maxWidth: 300, minWidth: 240 });
                this.clusterGroup.addLayer(marker);
            });

            // Update bottom stats dock
            const elOnline = document.getElementById('stat-online');
            const elOffline = document.getElementById('stat-offline');
            const elMaint = document.getElementById('stat-maintenance');
            const elTotal = document.getElementById('stat-total');
            if (elOnline) elOnline.textContent = online;
            if (elOffline) elOffline.textContent = offline;
            if (elMaint) elMaint.textContent = maintenance;
            if (elTotal) elTotal.textContent = total;
        },

        async toggleGapOverlay(enable) {
            this.showGapOverlay = enable;
            if (!enable) {
                if (this.gapOverlayLayer) {
                    this.map.removeLayer(this.gapOverlayLayer);
                    this.gapOverlayLayer = null;
                }
                return;
            }

            try {
                const res = await fetch('/api/v1/gap-analysis');
                const gapData = await res.json();

                if (this.gapOverlayLayer) {
                    this.map.removeLayer(this.gapOverlayLayer);
                }

                const featureCollection = {
                    type: 'FeatureCollection',
                    features: []
                };

                gapData.forEach(item => {
                    if (item.uncovered_geojson) {
                        featureCollection.features.push({
                            type: 'Feature',
                            properties: {
                                district_name: item.district_name,
                                camera_count: item.camera_count,
                                coverage_pct: item.coverage_pct,
                                uncovered_area_sq_km: item.uncovered_area_sq_km
                            },
                            geometry: item.uncovered_geojson
                        });
                    }
                });

                this.gapOverlayLayer = L.geoJSON(featureCollection, {
                    style: function(feature) {
                        return {
                            color: '#ef4444',
                            weight: 2,
                            opacity: 0.85,
                            fillColor: '#ef4444',
                            fillOpacity: 0.25
                        };
                    },
                    onEachFeature: function(feature, layer) {
                        const p = feature.properties;
                        layer.bindPopup(`
                            <div class="popup-content hud-bracket">
                                <div class="popup-title">
                                    <span class="badge-dot badge-dot--critical"></span>
                                    <span class="popup-name">Uncovered Region</span>
                                </div>
                                <div class="popup-details">
                                    <div class="popup-row">
                                        <span class="popup-label">District</span>
                                        <span class="popup-value">${p.district_name}</span>
                                    </div>
                                    <div class="popup-row">
                                        <span class="popup-label">Cameras</span>
                                        <span class="popup-value">${p.camera_count} active</span>
                                    </div>
                                    <div class="popup-row">
                                        <span class="popup-label">Coverage</span>
                                        <span class="popup-value">${p.coverage_pct}%</span>
                                    </div>
                                    <div class="popup-row">
                                        <span class="popup-label">Uncovered Area</span>
                                        <span class="popup-value">${p.uncovered_area_sq_km} sq km</span>
                                    </div>
                                </div>
                            </div>
                        `);
                    }
                });

                this.map.addLayer(this.gapOverlayLayer);
            } catch (e) {
                console.error('Failed to load gap-analysis overlay:', e);
            }
        },
    };
}
