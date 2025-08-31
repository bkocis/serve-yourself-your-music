document.addEventListener('DOMContentLoaded', function() {
    // Get the base path from the current URL
    const basePath = window.location.pathname.replace(/\/+$/, '');

    const mediaList = document.getElementById('media-list');
    const audioPlayer = document.getElementById('audio-element');
    const videoPlayer = document.getElementById('video-element');
    const audioPlayerContainer = document.getElementById('audio-player');
    const videoPlayerContainer = document.getElementById('video-player');
    const nowPlaying = document.getElementById('now-playing');
    const currentThumbnail = document.getElementById('current-thumbnail');
    const currentFilename = document.getElementById('current-filename');
    const currentFilenameVideo = document.getElementById('current-filename-video');
    const searchInput = document.getElementById('search-input');
    const tabButtons = document.querySelectorAll('.tab-button');
    const descriptionModal = document.getElementById('description-modal');
    const descriptionText = document.getElementById('description-text');
    const closeButton = document.querySelector('.description-modal-close');
    const sortSelect = document.getElementById('sort-select');
    const sortOrder = document.getElementById('sort-order');
    const deleteControls = document.querySelector('.delete-controls');
    const deleteSelectedButton = document.getElementById('delete-selected');
    const cancelDeleteButton = document.getElementById('cancel-delete');
    const playlistControls = document.querySelector('.playlist-controls');
    const playlistsList = document.querySelector('.playlists-list');
    const playlistsContainer = document.getElementById('playlists-container');
    const playlistNameInput = document.getElementById('playlist-name');
    const savePlaylistButton = document.getElementById('save-playlist');
    const cancelPlaylistButton = document.getElementById('cancel-playlist');

    let mediaFiles = [];
    let currentMediaType = 'all';
    let searchTerm = '';
    let currentSort = 'date_downloaded';
    let currentOrder = 'desc';
    let selectedFiles = new Set();
    let playlists = JSON.parse(localStorage.getItem('playlists') || '[]');
    let currentPlaylistIndex = -1;
    let currentPlaylist = null;
    let currentMedia = null;

    // Close modal when clicking the close button
    closeButton.addEventListener('click', function() {
        descriptionModal.style.display = 'none';
    });

    // Close modal when clicking outside
    window.addEventListener('click', function(event) {
        if (event.target === descriptionModal) {
            descriptionModal.style.display = 'none';
        }
    });

    // Playlist management
    savePlaylistButton.addEventListener('click', function() {
        const name = playlistNameInput.value.trim();
        if (!name) {
            alert('Please enter a playlist name');
            return;
        }

        if (selectedFiles.size === 0) {
            alert('Please select at least one track for the playlist');
            return;
        }

        const newPlaylist = {
            id: Date.now().toString(),
            name: name,
            tracks: Array.from(selectedFiles),
            createdAt: new Date().toISOString()
        };

        playlists.push(newPlaylist);
        localStorage.setItem('playlists', JSON.stringify(playlists));
        
        // Reset form and exit create playlist mode
        playlistNameInput.value = '';
        selectedFiles.clear();
        // Hide the playlist form
        document.querySelector('.playlist-form').style.display = 'none';
        exitCreatePlaylistMode();
        renderMediaList();
        renderPlaylists();
    });

    cancelPlaylistButton.addEventListener('click', function() {
        playlistNameInput.value = '';
        selectedFiles.clear();
        exitCreatePlaylistMode();
        renderMediaList();
    });

    function enterCreatePlaylistMode() {
        document.body.classList.add('create-playlist-mode');
        playlistControls.classList.remove('hidden');
        playlistsList.classList.add('hidden');
        // Hide the playlist form initially
        document.querySelector('.playlist-form').classList.add('hidden');
    }

    function exitCreatePlaylistMode() {
        document.body.classList.remove('create-playlist-mode');
        playlistControls.classList.add('hidden');
        // Hide the playlist form
        document.querySelector('.playlist-form').classList.add('hidden');
    }

    function renderPlaylists() {
        playlistsContainer.innerHTML = '';
        
        if (playlists.length === 0) {
            playlistsContainer.innerHTML = '<p class="loading">No playlists created yet</p>';
            return;
        }

        playlists.forEach(playlist => {
            const playlistCard = document.createElement('div');
            playlistCard.className = 'playlist-card';
            
            const trackCount = playlist.tracks.length;
            const createdAt = new Date(playlist.createdAt).toLocaleDateString();
            
            playlistCard.innerHTML = `
                <div class="playlist-card-header">
                    <div class="playlist-card-title">${playlist.name}</div>
                    <div class="playlist-card-actions">
                        <button class="playlist-card-play" onclick="event.stopPropagation(); playPlaylist('${playlist.id}')">Play</button>
                        <button class="playlist-card-delete" onclick="event.stopPropagation(); deletePlaylist('${playlist.id}')">Delete</button>
                    </div>
                </div>
                <div class="playlist-card-tracks">${trackCount} tracks</div>
                <div class="playlist-card-date">Created: ${createdAt}</div>
            `;

            playlistCard.addEventListener('click', function() {
                currentPlaylist = playlist;
                currentPlaylistIndex = 0;
                showPlaylistTracks(playlist);
            });

            playlistsContainer.appendChild(playlistCard);
        });
    }

    function showPlaylistTracks(playlist) {
        // Clear the playlists container
        playlistsContainer.innerHTML = '';
        
        // Create controls row with playlist header
        const controlsRow = document.createElement('div');
        controlsRow.className = 'playlist-controls-row';
        
        // Create playlist header with title and play button
        const playlistHeader = document.createElement('div');
        playlistHeader.className = 'playlist-header';
        playlistHeader.innerHTML = `
            <h2 class="playlist-title">${playlist.name}</h2>
            <div class="playlist-controls">
                <button class="play-button" onclick="window.playPlaylist('${playlist.id}')">Play Playlist</button>
            </div>
        `;

        // Add the playlist header to the controls row
        controlsRow.appendChild(playlistHeader);

        // Add the controls row to the container
        playlistsContainer.appendChild(controlsRow);

        // Create container for tracks
        const tracksContainer = document.createElement('div');
        tracksContainer.className = 'playlist-tracks-container';

        // Show playlist tracks
        playlist.tracks.forEach((trackPath, index) => {
            const file = mediaFiles.find(f => f.path === trackPath);
            if (file) {
                const trackItem = document.createElement('div');
                trackItem.className = 'media-item';
                trackItem.setAttribute('data-path', trackPath);
                trackItem.setAttribute('draggable', 'true');
                trackItem.innerHTML = `
                    <div class="drag-handle">⋮</div>
                    <div class="media-item-thumbnail">
                        <img src="${basePath}/thumbnail/${file.thumbnail}" alt="${file.name}">
                    </div>
                    <div class="media-item-info">
                        <div class="media-item-name">${file.name}</div>
                        <div class="media-item-details">${file.size}</div>
                    </div>
                `;

                // Add drag and drop event listeners
                trackItem.addEventListener('dragstart', function(e) {
                    this.classList.add('dragging');
                    e.dataTransfer.setData('text/plain', index.toString());
                });

                trackItem.addEventListener('dragend', function() {
                    this.classList.remove('dragging');
                    document.querySelectorAll('.media-item').forEach(item => {
                        item.classList.remove('drag-over');
                    });
                });

                trackItem.addEventListener('dragover', function(e) {
                    e.preventDefault();
                    const draggingItem = document.querySelector('.dragging');
                    if (draggingItem !== this) {
                        const rect = this.getBoundingClientRect();
                        const midY = rect.top + rect.height / 2;
                        if (e.clientY < midY) {
                            this.classList.add('drag-over');
                        } else {
                            this.classList.remove('drag-over');
                        }
                    }
                });

                trackItem.addEventListener('dragleave', function() {
                    this.classList.remove('drag-over');
                });

                trackItem.addEventListener('drop', function(e) {
                    e.preventDefault();
                    this.classList.remove('drag-over');
                    const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
                    const toIndex = Array.from(tracksContainer.children).indexOf(this);
                    
                    // Reorder the tracks array
                    const track = playlist.tracks[fromIndex];
                    playlist.tracks.splice(fromIndex, 1);
                    playlist.tracks.splice(toIndex, 0, track);
                    
                    // Update localStorage
                    localStorage.setItem('playlists', JSON.stringify(playlists));
                    
                    // Re-render the playlist
                    showPlaylistTracks(playlist);
                });

                trackItem.addEventListener('click', function() {
                    currentPlaylist = playlist;
                    currentPlaylistIndex = playlist.tracks.indexOf(trackPath);
                    playPlaylistItem();
                });

                tracksContainer.appendChild(trackItem);
            }
        });

        playlistsContainer.appendChild(tracksContainer);
    }

    // Delete mode handlers
    deleteSelectedButton.addEventListener('click', function() {
        if (selectedFiles.size === 0) {
            alert('Please select files to delete');
            return;
        }
        if (!confirm(`Are you sure you want to delete ${selectedFiles.size} file(s)?`)) {
            return;
        }
        const user = getCurrentUser();
        fetch(`${basePath}/delete`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ files: Array.from(selectedFiles), user })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Remove deleted files from the mediaFiles array and all playlists
                mediaFiles = mediaFiles.filter(file => !selectedFiles.has(file.path));
                playlists = playlists.map(playlist => ({
                    ...playlist,
                    tracks: playlist.tracks.filter(track => !selectedFiles.has(track))
                }));
                localStorage.setItem('playlists', JSON.stringify(playlists));
                selectedFiles.clear();
                // Exit delete mode
                exitDeleteMode();
                // Refresh the media list and playlists
                renderMediaList();
                renderPlaylists();
                alert(data.message);
            } else {
                alert(data.message);
            }
        })
        .catch(error => {
            console.error('Error deleting files:', error);
            alert('Error deleting files. Please try again.');
        });
    });

    cancelDeleteButton.addEventListener('click', function() {
        selectedFiles.clear();
        exitDeleteMode();
        renderMediaList();
    });

    function enterDeleteMode() {
        document.body.classList.add('delete-mode');
        deleteControls.classList.remove('hidden');
        playlistControls.classList.add('hidden');
        playlistsList.classList.add('hidden');
        // Disable player controls
        audioPlayer.disabled = true;
        videoPlayer.disabled = true;
    }

    function exitDeleteMode() {
        document.body.classList.remove('delete-mode');
        deleteControls.classList.add('hidden');
        if (currentMediaType === 'create-playlist') {
            playlistControls.classList.remove('hidden');
        } else if (currentMediaType === 'playlists') {
            playlistsList.classList.remove('hidden');
        }
        // Re-enable player controls
        audioPlayer.disabled = false;
        videoPlayer.disabled = false;
    }

    // Tab buttons
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const type = this.getAttribute('data-type');
            
            if (type === 'delete') {
                enterDeleteMode();
                exitCreatePlaylistMode();
                playlistsList.classList.add('hidden');
                mediaList.classList.remove('hidden');
            } else if (type === 'create-playlist') {
                exitDeleteMode();
                enterCreatePlaylistMode();
                playlistsList.classList.add('hidden');
                mediaList.classList.remove('hidden');
            } else if (type === 'playlists') {
                exitDeleteMode();
                exitCreatePlaylistMode();
                playlistsList.classList.remove('hidden');
                mediaList.classList.add('hidden');
                renderPlaylists();
            } else {
                exitDeleteMode();
                exitCreatePlaylistMode();
                playlistsList.classList.add('hidden');
                mediaList.classList.remove('hidden');
                selectedFiles.clear();
            }
            
            tabButtons.forEach(btn => btn.classList.remove('active'));
            this.classList.add('active');
            currentMediaType = type;
            renderMediaList();
        });
    });

    // Helper to get current user
    function getCurrentUser() {
        let user = localStorage.getItem('currentUser') || '';
        if (!user) {
            user = prompt('Please enter your username:');
            if (user) {
                user = user.trim();
                
                // Check if a user with the same normalized name already exists
                const registeredUsers = JSON.parse(localStorage.getItem('registeredUsers') || '[]');
                const normalizedUsername = user.toLowerCase();
                const existingUser = registeredUsers.find(u => u.toLowerCase() === normalizedUsername);
                
                if (existingUser) {
                    // Use existing username with original case for display
                    localStorage.setItem('currentUser', existingUser);
                    user = existingUser;
                } else {
                    // Store new username
                    registeredUsers.push(user);
                    localStorage.setItem('registeredUsers', JSON.stringify(registeredUsers));
                    localStorage.setItem('currentUser', user);
                }
                
                // Refresh the page to update the user-info display
                setTimeout(() => {
                    location.reload();
                }, 100);
            } else {
                user = '';
            }
        }
        return user.trim();
    }

    // Fetch media files from the server
    function fetchMediaFiles() {
        const user = getCurrentUser();
        fetch(`${basePath}/media?user=${encodeURIComponent(user)}`)
            .then(response => response.json())
            .then(data => {
                mediaFiles = data;
                renderMediaList();
            })
            .catch(error => {
                console.error('Error fetching media files:', error);
                mediaList.innerHTML = '<p class="loading">Error loading media files. Please try again.</p>';
            });
    }
    fetchMediaFiles();

    // Sort controls
    sortSelect.addEventListener('change', function() {
        currentSort = this.value;
        fetchAndRenderMedia();
    });

    sortOrder.addEventListener('change', function() {
        currentOrder = this.value;
        fetchAndRenderMedia();
    });

    // Search functionality
    searchInput.addEventListener('input', function() {
        searchTerm = this.value.toLowerCase();
        renderMediaList();
    });

    // Make playlist functions globally accessible
    window.playPlaylist = function(playlistId) {
        const playlist = playlists.find(p => p.id === playlistId);
        if (!playlist) return;

        currentPlaylist = playlist;
        currentPlaylistIndex = 0;
        playPlaylistItem();
    };

    window.playPlaylistItem = function() {
        if (currentPlaylist && currentPlaylistIndex >= 0 && currentPlaylistIndex < currentPlaylist.tracks.length) {
            const trackPath = currentPlaylist.tracks[currentPlaylistIndex];
            const fileInfo = mediaFiles.find(f => f.path === trackPath);
            
            if (fileInfo) {
                // Show the player container
                document.querySelector('.player-container').classList.remove('hidden');
                
                // Add basePath to stream and thumbnail URLs, include user param
                const user = getCurrentUser();
                const streamUrl = `${basePath}/stream/${trackPath}?user=${encodeURIComponent(user)}`;
                const thumbnailUrl = `${basePath}/thumbnail/${fileInfo.thumbnail}?user=${encodeURIComponent(user)}`;

                if (fileInfo.type === 'audio') {
                    // Show audio player, hide video player
                    audioPlayerContainer.classList.remove('hidden');
                    videoPlayerContainer.classList.add('hidden');

                    // Update audio player
                    audioPlayer.src = streamUrl;
                    audioPlayer.play();

                    // Update thumbnail
                    currentThumbnail.innerHTML = `<img src="${thumbnailUrl}" alt="${fileInfo.name}">`;

                    // Update now playing info
                    nowPlaying.textContent = 'Now Playing: ' + fileInfo.name;
                    currentFilename.textContent = fileInfo.name;
                    currentFilenameVideo.textContent = '';
                } else {
                    // Show video player, hide audio player
                    videoPlayerContainer.classList.remove('hidden');
                    audioPlayerContainer.classList.add('hidden');

                    // Update video player
                    videoPlayer.src = streamUrl;
                    videoPlayer.play();
                    
                    // Update filename display
                    currentFilenameVideo.textContent = fileInfo.name;
                    currentFilename.textContent = '';
                }
                
                // Update active state in the playlist view
                document.querySelectorAll('.playlist-tracks-container .media-item').forEach(item => {
                    item.classList.remove('active');
                });
                const currentItem = document.querySelector(`.playlist-tracks-container .media-item[data-path="${trackPath}"]`);
                if (currentItem) {
                    currentItem.classList.add('active');
                }
            }
        }
    };

    window.playNextInPlaylist = function() {
        if (currentPlaylist) {
            if (currentPlaylistIndex < currentPlaylist.tracks.length - 1) {
                currentPlaylistIndex++;
                playPlaylistItem();
            } else {
                currentPlaylistIndex = 0;
                playPlaylistItem();
            }
        } else if (currentMedia) {
            const currentIndex = mediaFiles.findIndex(file => file.path === currentMedia);
            if (currentIndex < mediaFiles.length - 1) {
                playMedia(mediaFiles[currentIndex + 1]);
            } else {
                playMedia(mediaFiles[0]);
            }
        }
    };

    window.playPreviousInPlaylist = function() {
        if (currentPlaylist) {
            if (currentPlaylistIndex > 0) {
                currentPlaylistIndex--;
                playPlaylistItem();
            } else {
                currentPlaylistIndex = currentPlaylist.tracks.length - 1;
                playPlaylistItem();
            }
        } else if (currentMedia) {
            const currentIndex = mediaFiles.findIndex(file => file.path === currentMedia);
            if (currentIndex > 0) {
                playMedia(mediaFiles[currentIndex - 1]);
            } else {
                playMedia(mediaFiles[mediaFiles.length - 1]);
            }
        }
    };

    // Handle audio player events
    audioPlayer.addEventListener('ended', function() {
        if (currentPlaylist) {
            // If we're playing from a playlist, play the next track
            if (currentPlaylistIndex < currentPlaylist.tracks.length - 1) {
                currentPlaylistIndex++;
                playPlaylistItem();
            } else {
                // If we've reached the end of the playlist, reset to the beginning
                currentPlaylistIndex = 0;
                playPlaylistItem();
            }
        } else if (currentMedia) {
            // If we're playing from the main list, play the next track
            const currentIndex = mediaFiles.findIndex(file => file.path === currentMedia);
            if (currentIndex < mediaFiles.length - 1) {
                playMedia(mediaFiles[currentIndex + 1]);
            } else {
                playMedia(mediaFiles[0]);
            }
        }
    });

    audioPlayer.addEventListener('error', function() {
        nowPlaying.textContent = 'Error playing this file';
    });

    // Render the media list based on current filters
    function renderMediaList() {
        let filteredFiles = mediaFiles;

        // Filter by media type
        if (currentMediaType !== 'all' && currentMediaType !== 'delete' && currentMediaType !== 'create-playlist' && currentMediaType !== 'playlists') {
            filteredFiles = filteredFiles.filter(file => file.type === currentMediaType);
        }

        // Filter by search term
        if (searchTerm) {
            filteredFiles = filteredFiles.filter(file =>
                file.name.toLowerCase().includes(searchTerm)
            );
        }

        // Clear the list
        mediaList.innerHTML = '';

        if (filteredFiles.length === 0) {
            mediaList.innerHTML = '<p class="loading">No media files found.</p>';
            return;
        }

        // Add each file to the list
        filteredFiles.forEach(file => {
            const mediaItem = document.createElement('div');
            mediaItem.classList.add('media-item');
            if (selectedFiles.has(file.path)) {
                mediaItem.classList.add('selected');
            }
            mediaItem.dataset.id = file.id;
            mediaItem.dataset.type = file.type;

            // Add basePath to thumbnail URL, include user param
            const user = getCurrentUser();
            const thumbnailUrl = `${basePath}/thumbnail/${file.thumbnail}?user=${encodeURIComponent(user)}`;

            mediaItem.innerHTML = `
                <input type="checkbox" class="checkbox" ${selectedFiles.has(file.path) ? 'checked' : ''}>
                <div class="media-item-thumbnail">
                    <img src="${thumbnailUrl}" alt="${file.name}">
                </div>
                <div class="media-item-info">
                    <div class="media-item-name">${file.name}</div>
                    <div class="media-item-details">${file.size}</div>
                </div>
                <span class="media-item-type ${file.type}">${file.type}</span>
                <button class="description-button" onclick="event.stopPropagation(); showDescription('${file.path}')">Description</button>
                <button class="add-to-playlist" onclick="event.stopPropagation(); addToPlaylist('${file.path}')">Add to Playlist</button>
            `;

            if (currentMediaType === 'delete') {
                mediaItem.addEventListener('click', function(e) {
                    if (e.target !== this.querySelector('.description-button') && 
                        e.target !== this.querySelector('.add-to-playlist')) {
                        const checkbox = this.querySelector('.checkbox');
                        if (selectedFiles.has(file.path)) {
                            selectedFiles.delete(file.path);
                            this.classList.remove('selected');
                            checkbox.checked = false;
                        } else {
                            selectedFiles.add(file.path);
                            this.classList.add('selected');
                            checkbox.checked = true;
                        }
                    }
                });
            } else if (currentMediaType === 'create-playlist') {
                mediaItem.addEventListener('click', function(e) {
                    if (e.target !== this.querySelector('.description-button') && 
                        e.target !== this.querySelector('.add-to-playlist')) {
                        const checkbox = this.querySelector('.checkbox');
                        if (selectedFiles.has(file.path)) {
                            selectedFiles.delete(file.path);
                            this.classList.remove('selected');
                            checkbox.checked = false;
                        } else {
                            selectedFiles.add(file.path);
                            this.classList.add('selected');
                            checkbox.checked = true;
                        }
                        // Show/hide playlist form based on selection
                        const playlistForm = document.querySelector('.playlist-form');
                        if (selectedFiles.size > 0) {
                            playlistForm.style.display = 'flex';
                        } else {
                            playlistForm.style.display = 'none';
                        }
                    }
                });
            } else {
                mediaItem.addEventListener('click', function() {
                    playMedia(file);

                    // Mark as active
                    document.querySelectorAll('.media-item').forEach(item => {
                        item.classList.remove('active');
                    });
                    this.classList.add('active');
                });
            }

            mediaList.appendChild(mediaItem);
        });
    }

    // Play the selected media
    function playMedia(file) {
        // Show the player container
        document.querySelector('.player-container').classList.remove('hidden');

        // Add basePath to stream and thumbnail URLs, include user param
        const user = getCurrentUser();
        const streamUrl = `${basePath}/stream/${file.path}?user=${encodeURIComponent(user)}`;
        const fileInfo = mediaFiles.find(f => f.path === file.path);
        if (!fileInfo) return;

        const thumbnailUrl = `${basePath}/thumbnail/${fileInfo.thumbnail}?user=${encodeURIComponent(user)}`;

        // Update current media
        currentMedia = file.path;

        if (fileInfo.type === 'audio') {
            // Show audio player, hide video player
            audioPlayerContainer.classList.remove('hidden');
            videoPlayerContainer.classList.add('hidden');

            // Update audio player
            audioPlayer.src = streamUrl;
            audioPlayer.play();

            // Update thumbnail
            currentThumbnail.innerHTML = `<img src="${thumbnailUrl}" alt="${fileInfo.name}">`;

            // Update now playing info
            nowPlaying.textContent = 'Now Playing: ' + fileInfo.name;
            currentFilename.textContent = fileInfo.name;
            currentFilenameVideo.textContent = '';
        } else {
            // Show video player, hide audio player
            videoPlayerContainer.classList.remove('hidden');
            audioPlayerContainer.classList.add('hidden');

            // Update video player
            videoPlayer.src = streamUrl;
            videoPlayer.play();
            
            // Update filename display
            currentFilenameVideo.textContent = fileInfo.name;
            currentFilename.textContent = '';
        }
    }

    // Add to playlist
    window.addToPlaylist = function(filePath) {
        if (!selectedFiles.has(filePath)) {
            selectedFiles.add(filePath);
            renderMediaList();
        }
    };

    // Delete playlist
    window.deletePlaylist = function(playlistId) {
        if (confirm('Are you sure you want to delete this playlist?')) {
            playlists = playlists.filter(p => p.id !== playlistId);
            localStorage.setItem('playlists', JSON.stringify(playlists));
            renderPlaylists();
        }
    };

    // Show description
    window.showDescription = function(filePath) {
        const user = getCurrentUser();
        fetch(`${basePath}/description/${filePath}?user=${encodeURIComponent(user)}`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    descriptionText.textContent = data.description;
                    descriptionModal.style.display = 'block';
                } else {
                    alert(data.message);
                }
            })
            .catch(error => {
                console.error('Error fetching description:', error);
                alert('Error fetching description');
            });
    };

    // Function to fetch and render media with current sort settings
    function fetchAndRenderMedia() {
        const user = getCurrentUser();
        fetch(`${basePath}/media?user=${encodeURIComponent(user)}&sort=${currentSort}&order=${currentOrder}`)
            .then(response => response.json())
            .then(data => {
                mediaFiles = data;
                renderMediaList();
            })
            .catch(error => {
                console.error('Error fetching media files:', error);
                mediaList.innerHTML = '<p class="loading">Error loading media files. Please try again.</p>';
            });
    }
});