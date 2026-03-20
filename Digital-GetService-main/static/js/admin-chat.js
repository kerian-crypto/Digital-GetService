(() => {
    const layout = document.querySelector('.chat-layout');
    if (!layout) {
        return;
    }

    const currentUserId = Number(layout.dataset.currentUserId || 0);
    const csrfToken = layout.dataset.csrfToken || '';
    const apiBase = layout.dataset.apiBase || '/backoffice/api';
    const wsUrl = layout.dataset.wsUrl || '';
    const wsToken = layout.dataset.wsToken || '';

    const usersContainer = document.getElementById('chatUsers');
    const messagesContainer = document.getElementById('chatMessages');
    const chatHeader = document.getElementById('chatHeader');
    const form = document.getElementById('chatForm');
    const input = document.getElementById('chatMessageInput');
    const sendButton = document.getElementById('chatSendButton');

    let users = [];
    let selectedUserId = null;
    let socket = null;
    let reconnectTimer = null;

    const withApi = (path) => `${apiBase.replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`;

    const escapeHtml = (value) => {
        const div = document.createElement('div');
        div.textContent = value;
        return div.innerHTML;
    };

    const setSocketState = (stateText) => {
        const current = chatHeader.textContent || '';
        if (!selectedUserId) {
            chatHeader.textContent = `WebSocket: ${stateText}. Selectionnez un utilisateur pour commencer.`;
            return;
        }
        if (!current.includes('|')) {
            chatHeader.textContent = `${current} | WS: ${stateText}`;
        } else {
            chatHeader.textContent = current.replace(/\| WS: .*$/, `| WS: ${stateText}`);
        }
    };

    const renderUsers = () => {
        usersContainer.innerHTML = users.map((user) => {
            const active = user.id === selectedUserId ? 'active' : '';
            return `
                <div class="chat-user-item ${active}" data-user-id="${user.id}">
                    <strong>${escapeHtml(user.full_name)}</strong>
                    <div class="small text-muted">${escapeHtml(user.email)} | ${escapeHtml(user.role)}</div>
                </div>
            `;
        }).join('');

        usersContainer.querySelectorAll('.chat-user-item').forEach((item) => {
            item.addEventListener('click', () => {
                const userId = Number(item.dataset.userId);
                if (selectedUserId === userId) {
                    return;
                }
                selectedUserId = userId;
                renderUsers();
                loadMessages();
            });
        });
    };

    const renderMessages = (messages) => {
        messagesContainer.innerHTML = messages.map((message) => {
            const bubbleType = Number(message.sender_id) === currentUserId ? 'self' : 'other';
            return `
                <div class="chat-bubble ${bubbleType}">
                    <div>${escapeHtml(message.content)}</div>
                    <span class="chat-meta">${escapeHtml(message.sender_name)} | ${escapeHtml(message.created_at)}</span>
                </div>
            `;
        }).join('');

        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    };

    const loadUsers = async () => {
        const response = await fetch(withApi('chat_users'), { credentials: 'same-origin' });
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        users = data.users || [];
        renderUsers();
    };

    const loadMessages = async () => {
        if (!selectedUserId) {
            return;
        }

        const response = await fetch(withApi(`chat_fetch?target_id=${selectedUserId}`), { credentials: 'same-origin' });
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        chatHeader.textContent = `Conversation avec ${data.target_user.full_name}`;
        setSocketState(socket && socket.readyState === WebSocket.OPEN ? 'connecte' : 'deconnecte');
        renderMessages(data.messages || []);
        input.disabled = false;
        sendButton.disabled = false;
    };

    const notifyWsNewMessage = (targetId, conversationId, messageId) => {
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            return;
        }

        socket.send(JSON.stringify({
            type: 'chat:new_message',
            target_user_id: targetId,
            sender_user_id: currentUserId,
            conversation_id: conversationId,
            message_id: messageId,
        }));
    };

    const sendMessage = async (message) => {
        if (!selectedUserId || !message.trim()) {
            return;
        }

        const response = await fetch(withApi('chat_send'), {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken,
            },
            body: JSON.stringify({
                target_id: selectedUserId,
                message: message.trim(),
            }),
        });

        if (!response.ok) {
            return;
        }

        const data = await response.json();
        await loadMessages();
        notifyWsNewMessage(Number(data.target_id), Number(data.conversation_id), Number(data.message_id));
    };

    const handleSocketMessage = async (event) => {
        try {
            const payload = JSON.parse(event.data);
            if (!payload || payload.type !== 'chat:new_message') {
                return;
            }

            const senderId = Number(payload.sender_user_id || 0);
            const targetId = Number(payload.target_user_id || 0);
            const concernsCurrentUser = senderId === currentUserId || targetId === currentUserId;
            if (!concernsCurrentUser) {
                return;
            }

            await loadUsers();
            if (selectedUserId && (selectedUserId === senderId || selectedUserId === targetId)) {
                await loadMessages();
            }
        } catch (error) {
            // ignore malformed payload
        }
    };

    const connectWebSocket = () => {
        if (!wsUrl || !wsToken) {
            setSocketState('indisponible');
            return;
        }

        try {
            const connector = wsUrl.includes('?') ? '&' : '?';
            socket = new WebSocket(`${wsUrl}${connector}token=${encodeURIComponent(wsToken)}`);
        } catch (error) {
            setSocketState('erreur');
            return;
        }

        socket.addEventListener('open', () => {
            setSocketState('connecte');
        });

        socket.addEventListener('message', handleSocketMessage);

        socket.addEventListener('close', () => {
            setSocketState('deconnecte');
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
            }
            reconnectTimer = setTimeout(connectWebSocket, 2000);
        });

        socket.addEventListener('error', () => {
            setSocketState('erreur');
        });
    };

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const message = input.value;
        input.value = '';
        await sendMessage(message);
        input.focus();
    });

    loadUsers();
    connectWebSocket();
})();
