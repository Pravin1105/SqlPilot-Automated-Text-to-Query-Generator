/**
 * SQLPilot Web — Client Application (Phase 3 Connected)
 *
 * Connects the web UI to the authoritative SQLPilot core backend:
 * - User ID & password authentication and session management
 * - Authorized database switching
 * - Real-time schema inspection via GET /api/schema
 * - Live database status via GET /api/status
 * - Natural-language query generation via POST /api/query/generate
 * - Automatic execution for safe READ queries
 * - Human-in-the-loop approval gating for modifying queries via POST /api/query/approve
 * - Explicit rejection handling via POST /api/query/reject
 */

(function () {
  "use strict";

  // Fallback mock schema if server API is unavailable in offline standalone mode
  const FALLBACK_SCHEMA = {
    database: "sample_store.db",
    tables: [
      {
        name: "customers",
        columns: [
          { name: "customer_id", type: "INTEGER", is_primary_key: true, is_unique: true, is_not_null: true, foreign_key: null },
          { name: "first_name", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "last_name", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "email", type: "TEXT", is_primary_key: false, is_unique: true, is_not_null: true, foreign_key: null },
          { name: "phone", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: false, foreign_key: null },
          { name: "city", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: false, foreign_key: null },
          { name: "state", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: false, foreign_key: null },
          { name: "created_at", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null }
        ]
      },
      {
        name: "products",
        columns: [
          { name: "product_id", type: "INTEGER", is_primary_key: true, is_unique: true, is_not_null: true, foreign_key: null },
          { name: "name", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "category", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "price", type: "REAL", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "stock_quantity", type: "INTEGER", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null }
        ]
      },
      {
        name: "orders",
        columns: [
          { name: "order_id", type: "INTEGER", is_primary_key: true, is_unique: true, is_not_null: true, foreign_key: null },
          { name: "customer_id", type: "INTEGER", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: "customers(customer_id)" },
          { name: "order_date", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "status", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "total_amount", type: "REAL", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null }
        ]
      },
      {
        name: "order_items",
        columns: [
          { name: "item_id", type: "INTEGER", is_primary_key: true, is_unique: true, is_not_null: true, foreign_key: null },
          { name: "order_id", type: "INTEGER", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: "orders(order_id)" },
          { name: "product_id", type: "INTEGER", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: "products(product_id)" },
          { name: "quantity", type: "INTEGER", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "unit_price", type: "REAL", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null }
        ]
      },
      {
        name: "payments",
        columns: [
          { name: "payment_id", type: "INTEGER", is_primary_key: true, is_unique: true, is_not_null: true, foreign_key: null },
          { name: "order_id", type: "INTEGER", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: "orders(order_id)" },
          { name: "payment_date", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "amount", type: "REAL", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null },
          { name: "payment_method", type: "TEXT", is_primary_key: false, is_unique: false, is_not_null: true, foreign_key: null }
        ]
      }
    ]
  };

  const MOCK_SCHEMA = FALLBACK_SCHEMA; // Backward-compatible alias
  const requiresApproval = true;
  const SAFETY_LEVELS = ["READ", "DML", "DDL", "DESTRUCTIVE"];

  const SAMPLE_QUESTIONS = {
    read: "Show top 5 customers by total spending this year.",
    filter: "List all products in the Electronics category.",
    dml: "Update stock quantity of MacBook Pro 16 to 30.",
    destructive: "Drop the payments table.",
    error: "SELECT * FROM non_existent_table;"
  };

  // DOM Elements
  const elements = {
    // Top Bar
    systemStateText: document.getElementById("systemStateText"),
    dbSelect: document.getElementById("dbSelect"),
    dbStatusDot: document.getElementById("dbStatusDot"),
    userBadge: document.getElementById("userBadge"),
    userName: document.getElementById("userName"),
    userRole: document.getElementById("userRole"),
    btnLogout: document.getElementById("btnLogout"),

    // Auth Modal
    authModal: document.getElementById("authModal"),
    authForm: document.getElementById("authForm"),
    loginUsername: document.getElementById("loginUsername"),
    loginPassword: document.getElementById("loginPassword"),
    authErrorBox: document.getElementById("authErrorBox"),
    authErrorMsg: document.getElementById("authErrorMsg"),
    btnLoginSubmit: document.getElementById("btnLoginSubmit"),
    btnCredAdmin: document.getElementById("btnCredAdmin"),
    btnCredAnalyst: document.getElementById("btnCredAnalyst"),

    // Upload / Local DB Modal
    btnOpenUploadModal: document.getElementById("btnOpenUploadModal"),
    uploadModal: document.getElementById("uploadModal"),
    btnCloseUploadModal: document.getElementById("btnCloseUploadModal"),
    uploadForm: document.getElementById("uploadForm"),
    fileDropzone: document.getElementById("fileDropzone"),
    dropzoneText: document.getElementById("dropzoneText"),
    dbFileInput: document.getElementById("dbFileInput"),
    btnUploadSubmit: document.getElementById("btnUploadSubmit"),
    uploadErrorBox: document.getElementById("uploadErrorBox"),
    uploadErrorMsg: document.getElementById("uploadErrorMsg"),
    inputLocalAgentUrl: document.getElementById("inputLocalAgentUrl"),
    inputLocalDbPath: document.getElementById("inputLocalDbPath"),
    agentStateLabel: document.getElementById("agentStateLabel"),
    connectionStateLabel: document.getElementById("connectionStateLabel"),

    // Settings Modal
    btnOpenSettingsModal: document.getElementById("btnOpenSettingsModal"),
    settingsModal: document.getElementById("settingsModal"),
    btnCloseSettingsModal: document.getElementById("btnCloseSettingsModal"),
    settingProvider: document.getElementById("settingProvider"),
    settingApiKey: document.getElementById("settingApiKey"),
    settingModel: document.getElementById("settingModel"),
    btnSaveSettings: document.getElementById("btnSaveSettings"),
    btnClearSettings: document.getElementById("btnClearSettings"),
    settingsStatusBox: document.getElementById("settingsStatusBox"),
    settingsStatusMsg: document.getElementById("settingsStatusMsg"),

    // Sidebar
    btnNewQuery: document.getElementById("btnNewQuery"),
    schemaTree: document.getElementById("schemaTree"),
    schemaSearchInput: document.getElementById("schemaSearchInput"),
    tableCountBadge: document.getElementById("tableCountBadge"),
    recentList: document.getElementById("recentList"),

    // Query Input
    queryInput: document.getElementById("queryInput"),
    btnRunQuery: document.getElementById("btnRunQuery"),
    btnClearPrompt: document.getElementById("btnClearPrompt"),
    sampleChips: document.querySelectorAll(".sample-chip"),

    // Stepper
    stepInput: document.getElementById("stepInput"),
    stepGen: document.getElementById("stepGen"),
    stepVal: document.getElementById("stepVal"),
    stepSafety: document.getElementById("stepSafety"),
    stepExec: document.getElementById("stepExec"),

    // SQL Panel
    sqlPanel: document.getElementById("sqlPanel"),
    safetyBadge: document.getElementById("safetyBadge"),
    generatedSqlText: document.getElementById("generatedSqlText"),
    explanationText: document.getElementById("explanationText"),
    btnCopySql: document.getElementById("btnCopySql"),
    copyBtnText: document.getElementById("copyBtnText"),

    // Approval Gate
    approvalGateBanner: document.getElementById("approvalGateBanner"),
    approvalWarningIcon: document.getElementById("approvalWarningIcon"),
    approvalBannerTitle: document.getElementById("approvalBannerTitle"),
    impactList: document.getElementById("impactList"),
    approvalPromptText: document.getElementById("approvalPromptText"),
    btnApproveQuery: document.getElementById("btnApproveQuery"),
    btnRejectQuery: document.getElementById("btnRejectQuery"),

    // Results Display
    resultsPanel: document.getElementById("resultsPanel"),
    resultRowCountBadge: document.getElementById("resultRowCountBadge"),
    executionTimeBadge: document.getElementById("executionTimeBadge"),
    resultsTableContainer: document.getElementById("resultsTableContainer"),
    resultsTable: document.getElementById("resultsTable"),
    resultsTableHead: document.getElementById("resultsTableHead"),
    resultsTableBody: document.getElementById("resultsTableBody"),

    // State Views
    emptyState: document.getElementById("emptyState"),
    loadingState: document.getElementById("loadingState"),
    loadingStateTitle: document.getElementById("loadingStateTitle"),
    errorState: document.getElementById("errorState"),
    errorTitle: document.getElementById("errorTitle"),
    errorMessage: document.getElementById("errorMessage")
  };

  // State
  let sessionToken = localStorage.getItem("sqlpilot_session_token") || "";
  let currentUser = null;
  let loadedTables = [];
  const isDirectConsole = window.location.port === "8765";
  const isLocalHost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  const DEFAULT_AGENT_URL = (isDirectConsole || isLocalHost)
    ? `${window.location.protocol}//${window.location.host}`
    : "http://127.0.0.1:8765";

  let localAgentUrl = (isDirectConsole || (isLocalHost && window.location.port === "8765"))
    ? window.location.origin
    : (localStorage.getItem("sqlpilot_local_agent_url") || DEFAULT_AGENT_URL);

  // Purge any stale HTTPS local agent URLs stored in localStorage
  if (localAgentUrl.startsWith("https://127.0.0.1") || localAgentUrl.startsWith("https://localhost")) {
    localAgentUrl = localAgentUrl.replace(/^https:/, "http:");
    localStorage.setItem("sqlpilot_local_agent_url", localAgentUrl);
  }
  if (isDirectConsole) {
    localAgentUrl = window.location.origin;
    localStorage.setItem("sqlpilot_local_agent_url", localAgentUrl);
  }
  let localSchema = null;
  let isLocalAgentConnected = false;
  let recentQueries = [
    "Show top 5 customers by total spending this year.",
    "List all products in the Electronics category.",
    "What is the total revenue generated from completed orders?"
  ];

  let selectedUploadFile = null;

  // --- Authenticated Fetch Helper ---
  async function fetchWithAuth(url, options = {}) {
    const headers = options.headers || {};
    if (sessionToken) {
      headers["Authorization"] = `Bearer ${sessionToken}`;
    }

    // Inject user-configured LLM credentials if set
    const userApiKey = localStorage.getItem("sqlpilot_user_api_key");
    const userProvider = localStorage.getItem("sqlpilot_user_provider") || "groq";
    const userModel = localStorage.getItem("sqlpilot_user_model") || "";
    if (userApiKey) {
      headers["X-LLM-Api-Key"] = userApiKey;
      headers["X-LLM-Provider"] = userProvider;
      if (userModel) {
        headers["X-LLM-Model"] = userModel;
      }
    }

    const mergedOptions = { ...options, headers };

    const resp = await fetch(url, mergedOptions);
    if (resp.status === 401) {
      // Session expired or unauthenticated
      handleAuthRequired();
      throw new Error("Authentication required. Please log in.");
    }
    return resp;
  }

  function handleAuthRequired() {
    sessionToken = "";
    currentUser = null;
    localStorage.removeItem("sqlpilot_session_token");
    setSystemState("Auth Required");
    showAuthModal();
  }

  function showAuthModal() {
    if (elements.authModal) {
      elements.authModal.classList.remove("hidden");
      elements.authErrorBox.classList.add("hidden");
      elements.loginUsername.focus();
    }
  }

  function hideAuthModal() {
    if (elements.authModal) {
      elements.authModal.classList.add("hidden");
    }
  }

  // --- Initialization ---
  async function init() {
    attachEventListeners();
    renderRecentQueries();

    // Verify session or prompt login
    if (sessionToken) {
      try {
        const resp = await fetchWithAuth("/api/auth/me");
        if (resp.ok) {
          const data = await resp.json();
          currentUser = data.user;
          updateUserBadge(currentUser);
          hideAuthModal();

          // Probe Local Agent for Hybrid Architecture
          await checkLocalAgent();
          if (!isLocalAgentConnected) {
            await loadDatabases();
            await fetchBackendSchema();
            await fetchBackendStatus();
          }
          setSystemState("Ready");
          return;
        }
      } catch (e) {
        // Fall through to auto-login or login modal
      }
    }

    // Auto-login for local all-in-one console (port 8765 or localhost)
    if (isDirectConsole || isLocalHost) {
      try {
        const autoResp = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: jsonSafe({ username: "local_user", password: "local_password" })
        });
        if (autoResp.ok) {
          const autoData = await autoResp.json();
          if (autoData.success) {
            sessionToken = autoData.token;
            currentUser = autoData.user;
            localStorage.setItem("sqlpilot_session_token", sessionToken);
            updateUserBadge(currentUser);
            hideAuthModal();
            await checkLocalAgent();
            setSystemState("Ready");
            return;
          }
        }
      } catch (e) {
        // Fall back to showing login modal if auto-login fails
      }
    }

    // If unauthenticated or no valid token, show modal
    showAuthModal();
    setSystemState("Sign In Required");
  }

  function updateUserBadge(user) {
    if (!user) return;
    if (elements.userName) elements.userName.textContent = user.username;
    if (elements.userRole) elements.userRole.textContent = user.role.toUpperCase();
  }

  // --- Auth Handlers ---
  async function handleLogin(username, password) {
    elements.authErrorBox.classList.add("hidden");
    elements.btnLoginSubmit.disabled = true;
    elements.btnLoginSubmit.textContent = "Authenticating...";

    try {
      const resp = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonSafe({ username, password })
      });

      let data;
      try {
        data = await resp.json();
      } catch (jsonErr) {
        throw new Error(`Server returned status ${resp.status} (${resp.statusText || "Non-JSON response"})`);
      }

      if (resp.ok && data.success) {
        sessionToken = data.token;
        currentUser = data.user;
        localStorage.setItem("sqlpilot_session_token", sessionToken);
        updateUserBadge(currentUser);
        hideAuthModal();

        // Immediately probe and sync Local Agent upon login
        await checkLocalAgent();
        if (!isLocalAgentConnected) {
          await loadDatabases();
          await fetchBackendSchema();
          await fetchBackendStatus();
        }
        setSystemState("Ready");
      } else {
        elements.authErrorMsg.textContent = data.error || "Authentication failed.";
        elements.authErrorBox.classList.remove("hidden");
      }
    } catch (err) {
      elements.authErrorMsg.textContent = err.message || "Failed to connect to authentication service.";
      elements.authErrorBox.classList.remove("hidden");
    } finally {
      elements.btnLoginSubmit.disabled = false;
      elements.btnLoginSubmit.textContent = "Authenticate & Access";
    }
  }

  async function handleLogout() {
    if (sessionToken) {
      try {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${sessionToken}`
          },
          body: jsonSafe({ token: sessionToken })
        });
      } catch (e) {
        // Ignore network failures on logout
      }
    }

    handleAuthRequired();
  }

  // --- Database Switching ---
  async function loadDatabases() {
    try {
      const resp = await fetchWithAuth("/api/databases");
      if (resp.ok) {
        const data = await resp.json();
        if (data.databases && elements.dbSelect) {
          elements.dbSelect.innerHTML = "";
          data.databases.forEach(db => {
            const opt = document.createElement("option");
            opt.value = db.name;
            opt.textContent = db.is_authorized ? db.name : `🔒 ${db.name} (Restricted)`;
            if (db.is_current) {
              opt.selected = true;
            }
            if (!db.is_authorized) {
              opt.disabled = true;
            }
            elements.dbSelect.appendChild(opt);
          });
        }
      }
    } catch (e) {
      // In offline preview mode, leave default
    }
  }

  async function handleDatabaseSwitch(targetDb) {
    if (!targetDb) return;
    setSystemState("Switching DB...");

    try {
      if (isLocalAgentConnected) {
        // Architecture invariant: Local Agent owns database connection & schema extraction
        const cleanUrl = getValidAgentUrl(localAgentUrl);
        const connResp = await fetch(`${cleanUrl}/agent/connect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: jsonSafe({ db_path: targetDb })
        });
        const connData = await connResp.json();
        if (connResp.ok && connData.success && connData.schema) {
          localSchema = connData.schema;
          loadedTables = connData.schema.tables || [];
          renderSchemaTree(loadedTables);

          // Synchronize schema metadata to Vercel for Schema RAG & LLM prompt
          try {
            await fetchWithAuth("/api/schema/sync", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: jsonSafe({ schema: connData.schema })
            });
          } catch (syncErr) {
            console.warn("[LocalAgent] Schema sync skipped:", syncErr);
          }

          resetSession();
          setSystemState("Ready");
          showToast(`Switched to local database: ${connData.database || targetDb}`, "success");
          return;
        }
      }

      // If switching among already synced schemas on Vercel
      const resp = await fetchWithAuth("/api/database/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonSafe({ database: targetDb })
      });

      const data = await resp.json();
      if (resp.ok && data.success) {
        resetSession();
        await fetchBackendSchema();
        await fetchBackendStatus();
        setSystemState("Ready");
      } else {
        alert(data.error || "Failed to switch database.");
        await loadDatabases(); // Revert selection
        setSystemState("Ready");
      }
    } catch (err) {
      alert("Error switching database: " + err.message);
      await loadDatabases();
      setSystemState("Ready");
    }
  }

  // --- API Calls ---
  async function fetchBackendStatus() {
    try {
      const resp = await fetchWithAuth("/api/status");
      if (resp.ok) {
        const data = await resp.json();
        if (data.database && elements.dbSelect) {
          for (let i = 0; i < elements.dbSelect.options.length; i++) {
            if (elements.dbSelect.options[i].value === data.database) {
              elements.dbSelect.selectedIndex = i;
              break;
            }
          }
        }
      }
    } catch (e) {
      // Ignore
    }
  }

  async function fetchBackendSchema() {
    try {
      const resp = await fetchWithAuth("/api/schema");
      if (resp.ok) {
        const data = await resp.json();
        if (data.tables && data.tables.length > 0) {
          loadedTables = data.tables;
          renderSchemaTree(loadedTables);
          return;
        }
      }
    } catch (e) {
      // Fallback
    }

    loadedTables = FALLBACK_SCHEMA.tables;
    renderSchemaTree(loadedTables);
  }

  function getValidAgentUrl(url) {
    if (!url || typeof url !== "string") return "http://127.0.0.1:8765";
    const trimmed = url.trim().replace(/\/+$/, "");
    if (!trimmed || !trimmed.startsWith("http")) return "http://127.0.0.1:8765";
    return trimmed;
  }

  function markLocalAgentOffline() {
    isLocalAgentConnected = false;
    if (elements.agentStateLabel) {
      elements.agentStateLabel.textContent = "Offline (127.0.0.1:8765)";
      elements.agentStateLabel.style.color = "var(--accent-danger)";
    }
    if (elements.connectionStateLabel) {
      elements.connectionStateLabel.textContent = "Offline";
      elements.connectionStateLabel.className = "status-text disconnected";
    }
  }

  // --- Local Agent Interaction (Hybrid Cloud/Local Architecture) ---
  async function checkLocalAgent() {
    let cleanUrl = getValidAgentUrl(localAgentUrl);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);
      let resp;
      try {
        resp = await fetch(`${cleanUrl}/agent/status`, {
          signal: controller.signal,
          headers: { "Content-Type": "application/json" }
        });
      } catch (directErr) {
        if (cleanUrl.includes("127.0.0.1")) {
          try {
            const altUrl = cleanUrl.replace("127.0.0.1", "localhost");
            const altResp = await fetch(`${altUrl}/agent/status`, {
              signal: controller.signal,
              headers: { "Content-Type": "application/json" }
            });
            if (altResp && altResp.ok) {
              resp = altResp;
              cleanUrl = altUrl;
              localAgentUrl = altUrl;
              localStorage.setItem("sqlpilot_local_agent_url", localAgentUrl);
            }
          } catch (altErr) {
            // failed
          }
        }
        if (!resp) {
          clearTimeout(timeoutId);
          markLocalAgentOffline();
          return false;
        }
      }
      clearTimeout(timeoutId);

      if (resp && resp.ok) {
        const data = await resp.json();
        isLocalAgentConnected = !!data.connected;

        if (elements.agentStateLabel) {
          elements.agentStateLabel.textContent = data.connected
            ? `${data.database || "Connected"}`
            : "Agent Ready (No DB)";
          elements.agentStateLabel.style.color = data.connected ? "var(--accent-active)" : "var(--accent-warn)";
        }
        if (elements.connectionStateLabel) {
          elements.connectionStateLabel.textContent = data.connected ? "Connected" : "No DB";
          elements.connectionStateLabel.className = data.connected ? "status-text connected" : "status-text warning";
        }

        if (data.connected) {
          // Fetch schema metadata directly from local agent (Zero rows/records)
          let sResp;
          try {
            sResp = await fetch(`${cleanUrl}/agent/schema`);
          } catch (e) {
            sResp = null;
          }

          if (sResp && sResp.ok) {
            const sData = await sResp.json();
            if (sData.tables && sData.tables.length > 0) {
              localSchema = sData;
              loadedTables = sData.tables;
              renderSchemaTree(loadedTables);

              // Sync schema metadata to Vercel in background for Schema RAG & LLM prompt
              try {
                await fetchWithAuth("/api/schema/sync", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: jsonSafe({ schema: sData })
                });
              } catch (syncErr) {
                // Background sync failure won't block UI
              }

              // Update DB dropdown to show local database
              if (elements.dbSelect) {
                elements.dbSelect.innerHTML = "";
                const opt = document.createElement("option");
                opt.value = data.database;
                opt.textContent = `💻 Local: ${data.database}`;
                opt.selected = true;
                elements.dbSelect.appendChild(opt);
              }

              setSystemState("Local Agent Connected");
              return true;
            }
          }
        }
        return true;
      }
    } catch (e) {
      // Local agent not reachable
    }

    isLocalAgentConnected = false;
    if (elements.agentStateLabel) {
      elements.agentStateLabel.textContent = "Offline (127.0.0.1:8765)";
      elements.agentStateLabel.style.color = "var(--text-muted)";
    }
    if (elements.connectionStateLabel) {
      elements.connectionStateLabel.textContent = "Disconnected";
      elements.connectionStateLabel.className = "status-text error";
    }
    return false;
  }

  function jsonSafe(obj) {
    return JSON.stringify(obj);
  }

  function setSystemState(stateText) {
    if (elements.systemStateText) {
      elements.systemStateText.textContent = stateText;
    }
  }

  // --- Schema Tree Renderer ---
  function renderSchemaTree(tables, filterText = "") {
    elements.schemaTree.innerHTML = "";
    const cleanFilter = filterText.trim().toLowerCase();

    let renderedCount = 0;
    tables.forEach(table => {
      const tableNameMatches = table.name.toLowerCase().includes(cleanFilter);
      const matchingCols = (table.columns || []).filter(c =>
        c.name.toLowerCase().includes(cleanFilter) || (c.type && c.type.toLowerCase().includes(cleanFilter))
      );

      if (cleanFilter && !tableNameMatches && matchingCols.length === 0) {
        return;
      }

      renderedCount++;
      const tableNode = document.createElement("div");
      tableNode.className = "schema-table-item";

      const header = document.createElement("div");
      header.className = "schema-table-header";
      header.setAttribute("role", "button");
      header.setAttribute("tabindex", "0");
      header.setAttribute("aria-expanded", "false");

      const headerLeft = document.createElement("div");
      headerLeft.className = "table-header-left";

      const arrow = document.createElement("span");
      arrow.className = "table-toggle-arrow";
      arrow.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>`;

      const icon = document.createElement("span");
      icon.className = "table-icon";
      icon.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>`;

      const name = document.createElement("span");
      name.className = "table-name";
      name.textContent = table.name;
      name.title = table.name;

      headerLeft.appendChild(arrow);
      headerLeft.appendChild(icon);
      headerLeft.appendChild(name);

      const badge = document.createElement("span");
      badge.className = "table-col-count";
      const colCount = (table.columns || []).length;
      badge.textContent = `${colCount} col${colCount === 1 ? "" : "s"}`;

      header.appendChild(headerLeft);
      header.appendChild(badge);

      const colList = document.createElement("div");
      colList.className = "schema-col-list";

      const colsToRender = cleanFilter && !tableNameMatches ? matchingCols : (table.columns || []);
      colsToRender.forEach(col => {
        const colRow = document.createElement("div");
        colRow.className = "schema-col-row";

        const colLeft = document.createElement("div");
        colLeft.className = "col-left";

        const colName = document.createElement("span");
        colName.className = "col-name";
        colName.textContent = col.name;

        const colType = document.createElement("span");
        colType.className = "col-type";
        colType.textContent = col.type || "";

        colLeft.appendChild(colName);
        if (col.type) {
          colLeft.appendChild(colType);
        }

        const tagsContainer = document.createElement("div");
        tagsContainer.className = "col-tags";

        // 1. Primary Key Tag
        if (col.is_primary_key) {
          const pkTag = document.createElement("span");
          pkTag.className = "col-tag tag-pk";
          pkTag.textContent = "PK";
          pkTag.title = "Primary Key";
          tagsContainer.appendChild(pkTag);
        }

        // 2. Unique Tag
        if (col.is_unique) {
          const uqTag = document.createElement("span");
          uqTag.className = "col-tag tag-unique";
          uqTag.textContent = "UNIQUE";
          uqTag.title = "Unique Constraint";
          tagsContainer.appendChild(uqTag);
        }

        // 3. Not Null Tag
        if (col.is_not_null || (!col.is_nullable && !col.is_primary_key)) {
          const nnTag = document.createElement("span");
          nnTag.className = "col-tag tag-notnull";
          nnTag.textContent = "NOT NULL";
          nnTag.title = "Not Null Constraint";
          tagsContainer.appendChild(nnTag);
        }

        // 4. Foreign Key Tag
        if (col.foreign_key) {
          const fkTag = document.createElement("span");
          fkTag.className = "col-tag tag-fk";
          const fkTarget = col.foreign_key.split("(")[0];
          fkTag.textContent = `FK ➔ ${fkTarget}`;
          fkTag.title = `Foreign Key referencing ${col.foreign_key}`;
          tagsContainer.appendChild(fkTag);
        }

        colRow.appendChild(colLeft);
        colRow.appendChild(tagsContainer);
        colList.appendChild(colRow);
      });

      function toggleTable() {
        const isExpanded = tableNode.classList.toggle("expanded");
        header.setAttribute("aria-expanded", isExpanded ? "true" : "false");
        arrow.style.transform = isExpanded ? "rotate(90deg)" : "rotate(0deg)";
      }

      header.addEventListener("click", toggleTable);
      header.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleTable();
        }
      });

      if (cleanFilter) {
        tableNode.classList.add("expanded");
        header.setAttribute("aria-expanded", "true");
        arrow.style.transform = "rotate(90deg)";
      }

      tableNode.appendChild(header);
      tableNode.appendChild(colList);
      elements.schemaTree.appendChild(tableNode);
    });

    elements.tableCountBadge.textContent = `${renderedCount} table${renderedCount === 1 ? "" : "s"}`;
  }

  // --- Stepper Navigation ---
  function updateStepper(activeStep) {
    const steps = [
      { id: "stepInput", name: "input" },
      { id: "stepGen", name: "gen" },
      { id: "stepVal", name: "val" },
      { id: "stepSafety", name: "safety" },
      { id: "stepExec", name: "exec" }
    ];

    let passed = true;
    steps.forEach(s => {
      const el = elements[s.id];
      if (!el) return;
      el.classList.remove("active", "completed");
      if (s.name === activeStep) {
        el.classList.add("active");
        passed = false;
      } else if (passed) {
        el.classList.add("completed");
      }
    });
  }

  // --- Primary Workflow: Query Generation & Routing ---
  async function runQueryFlow(rawQuestion) {
    const question = rawQuestion.trim();
    if (!question) {
      showError("Empty Query", "Please enter a question or SQL intent to begin.");
      return;
    }

    if (!sessionToken) {
      showAuthModal();
      return;
    }

    // Reset UI state
    hideApprovalGate();
    elements.errorState.classList.add("hidden");
    elements.resultsTableContainer.classList.add("hidden");
    elements.emptyState.classList.add("hidden");
    pendingApprovalState = null;

    // Step 1: Input
    updateStepper("input");
    setSystemState("Processing Input...");

    // Add to recents
    if (!recentQueries.includes(question)) {
      recentQueries.unshift(question);
      if (recentQueries.length > 5) recentQueries.pop();
      renderRecentQueries();
    }

    // Step 2: Ensure Local Agent & Schema are ready
    setTimeout(() => updateStepper("gen"), 150);
    showLoading("Verifying local database connection...");

    if (!isLocalAgentConnected || !localSchema) {
      await checkLocalAgent();
    }

    if (!isLocalAgentConnected || !localSchema) {
      hideLoading();
      setSystemState("Local Agent Required");
      updateStepper("input");
      showError(
        "Local Agent Not Connected",
        "SQLPilot requires the local agent to run queries against your local SQLite database without exposing data to the cloud.<br><br>" +
        "Please ensure your local agent is running in your terminal:<br>" +
        "<pre style='background:#0f172a; color:#38bdf8; padding:8px 12px; border-radius:6px; margin:8px 0; font-family:monospace;'>python -m sqlpilot.agent --db ./data/sample_store.db</pre>" +
        "Then click 'Run Query' again."
      );
      return;
    }

    showLoading("Chunking schema metadata & generating SQL with offline privacy guard...");

    try {
      const payload = {
        question,
        schema: localSchema,
        execute_cloud: false
      };

      const resp = await fetchWithAuth("/api/query/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonSafe(payload)
      });

      const data = await resp.json();

      if (!resp.ok || !data.success) {
        hideLoading();
        setSystemState("Error");
        updateStepper("val");
        showError("Generation Failed", data.error || "Could not generate or validate SQL.");
        if (data.sql) {
          elements.generatedSqlText.textContent = data.sql;
        }
        return;
      }

      // Handle Ambiguity
      if (data.is_ambiguous) {
        hideLoading();
        setSystemState("Clarification Needed");
        updateStepper("input");
        showClarificationOptions(data.clarification_options || []);
        return;
      }

      // Display Generated SQL & Explanation
      elements.generatedSqlText.textContent = data.sql;
      elements.explanationText.textContent = data.explanation || "No explanation provided.";

      // Step 4: Safety Classification
      updateStepper("safety");
      applySafetyBadge(data.safety_level);

      // Step 5: Routing Decision
      if (data.requires_approval) {
        // Modifying operation halted at Human-in-the-Loop Gate
        hideLoading();
        setSystemState("Awaiting User Approval");
        pendingApprovalState = {
          token: data.pending_token,
          sql: data.sql,
          explanation: data.explanation,
          safety_level: data.safety_level,
          affected_tables: data.affected_tables || [],
          is_local: true
        };
        showApprovalGate(data);
      } else {
        // Safe READ query: Execute DIRECTLY on Local SQLite Agent (Zero records to Vercel)
        showLoading("Executing query locally via SQLite (zero data leaves localhost)...");
        try {
          const cleanUrl = getValidAgentUrl(localAgentUrl);
          const execResp = await fetch(`${cleanUrl}/agent/execute`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: jsonSafe({ sql: data.sql })
          });
          const execData = await execResp.json();
          if (!execResp.ok || !execData.success) {
            hideLoading();
            setSystemState("Execution Failed");
            showError("Local Execution Error", execData.error || "Local SQLite execution failed.");
            return;
          }
          updateStepper("exec");
          setSystemState("Complete (Local SQLite)");
          renderResultsTable(execData.columns || [], execData.rows || [], execData.execution_time_ms || 0);
        } catch (execErr) {
          hideLoading();
          setSystemState("Execution Failed");
          showError("Local Agent Connection Error", `Failed to execute on local agent: ${execErr.message}`);
        }
      }
    } catch (err) {
      hideLoading();
      setSystemState("Error");
      showError("Connection Error", err.message || "Failed to reach backend server.");
    }
  }

  function applySafetyBadge(level) {
    elements.safetyBadge.textContent = level;
    elements.safetyBadge.className = `safety-badge ${level.toLowerCase()}`;
  }

  function showClarificationOptions(options) {
    elements.emptyState.classList.add("hidden");
    elements.resultsTableContainer.classList.add("hidden");
    elements.errorState.classList.add("hidden");
    elements.loadingState.classList.add("hidden");

    let optionsHtml = "<p style='margin-bottom:8px;'>The request is ambiguous. Please choose a clarification:</p><ul style='padding-left:18px; line-height:1.6;'>";
    options.forEach(opt => {
      optionsHtml += `<li><strong>${opt}</strong></li>`;
    });
    optionsHtml += "</ul>";

    showError("Clarification Needed", optionsHtml);
  }

  // --- Approval Gate Handlers ---
  function showApprovalGate(data) {
    elements.approvalGateBanner.classList.remove("hidden");
    elements.approvalBannerTitle.textContent = `${data.safety_level} Operation Requires Approval`;

    elements.impactList.innerHTML = "";
    (data.impact || []).forEach(statement => {
      const li = document.createElement("li");
      li.textContent = statement;
      elements.impactList.appendChild(li);
    });

    elements.approvalPromptText.textContent =
      `Please review the generated SQL statement above carefully. Explicit user approval is mandatory prior to modifying the database.`;
  }

  function hideApprovalGate() {
    elements.approvalGateBanner.classList.add("hidden");
  }

  async function handleApprove() {
    if (!pendingApprovalState) return;

    const token = pendingApprovalState.token;
    const sql = elements.generatedSqlText.textContent.trim();
    const isLocal = pendingApprovalState.is_local;

    hideApprovalGate();
    showLoading("Executing approved modification against local database...");
    setSystemState("Executing Modification...");

    try {
      const cleanUrl = getValidAgentUrl(localAgentUrl);
      const resp = await fetch(`${cleanUrl}/agent/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonSafe({ sql, token })
      });
      const data = await resp.json();

      if (!data || !data.success) {
        hideLoading();
        setSystemState("Execution Failed");
        showError("Execution Error", (data && data.error) || "Database execution failed.");
        return;
      }

      // Success
      updateStepper("exec");
      setSystemState("Complete (Local SQLite)");
      pendingApprovalState = null;

      if (data.rows && data.rows.length > 0) {
        renderResultsTable(data.columns || [], data.rows, data.execution_time_ms || 0);
      } else {
        showEmptyResultsPrompt(`Success: Query executed. Affected ${data.affected_rows || 0} row(s).`);
        elements.resultRowCountBadge.textContent = `${data.affected_rows || 0} affected`;
        elements.executionTimeBadge.textContent = `${Number(data.execution_time_ms || 0).toFixed(2)} ms`;
      }

      // Refresh schema in case of DDL modifications
      if (isLocal) {
        await checkLocalAgent();
      } else {
        fetchBackendSchema();
      }
    } catch (err) {
      hideLoading();
      setSystemState("Error");
      showError("Approval Error", err.message || "Approval submission failed.");
    }
  }

  async function handleReject() {
    if (!pendingApprovalState) return;

    const token = pendingApprovalState.token;
    try {
      await fetchWithAuth("/api/query/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonSafe({ token })
      });
    } catch (e) {
      // Still close gate on frontend
    }

    pendingApprovalState = null;
    hideApprovalGate();
    setSystemState("Ready");
    updateStepper("input");
    showError("Operation Cancelled", "The user declined execution. The database state remains unchanged.");
  }

  // --- Results Table Renderer ---
  function renderResultsTable(columns, rows, executionTimeMs) {
    hideLoading();
    elements.emptyState.classList.add("hidden");
    elements.errorState.classList.add("hidden");
    elements.resultsTableContainer.classList.remove("hidden");

    elements.resultRowCountBadge.textContent = `${rows.length} row${rows.length === 1 ? "" : "s"}`;
    elements.executionTimeBadge.textContent = `${Number(executionTimeMs).toFixed(2)} ms`;

    elements.resultsTableHead.innerHTML = "";
    const trHead = document.createElement("tr");
    columns.forEach(colName => {
      const th = document.createElement("th");
      th.textContent = colName;
      trHead.appendChild(th);
    });
    elements.resultsTableHead.appendChild(trHead);

    elements.resultsTableBody.innerHTML = "";
    rows.forEach(row => {
      const tr = document.createElement("tr");
      columns.forEach(colName => {
        const td = document.createElement("td");
        td.textContent = row[colName] !== undefined && row[colName] !== null ? row[colName] : "";
        tr.appendChild(td);
      });
      elements.resultsTableBody.appendChild(tr);
    });
  }

  // --- View Helpers ---
  function showLoading(message) {
    elements.emptyState.classList.add("hidden");
    elements.errorState.classList.add("hidden");
    elements.resultsTableContainer.classList.add("hidden");
    elements.loadingState.classList.remove("hidden");
    if (message) {
      elements.loadingStateTitle.textContent = message;
    }
  }

  function hideLoading() {
    elements.loadingState.classList.add("hidden");
  }

  function showEmptyResultsPrompt(subtitle) {
    hideLoading();
    elements.resultsTableContainer.classList.add("hidden");
    elements.errorState.classList.add("hidden");
    elements.emptyState.classList.remove("hidden");
    if (subtitle) {
      elements.emptyState.querySelector(".state-subtitle").textContent = subtitle;
    }
  }

  function showError(title, message) {
    hideLoading();
    elements.resultsTableContainer.classList.add("hidden");
    elements.emptyState.classList.add("hidden");
    elements.errorState.classList.remove("hidden");
    elements.errorTitle.textContent = title;
    if (typeof message === "string" && !message.includes("<p") && !message.includes("<ul") && !message.includes("<div")) {
      elements.errorMessage.textContent = message;
    } else {
      elements.errorMessage.innerHTML = message;
    }
  }

  function resetSession() {
    elements.queryInput.value = "";
    elements.generatedSqlText.textContent = "-- Generated SQL will appear here";
    elements.explanationText.textContent = "Query explanation will appear here after generation.";
    elements.safetyBadge.textContent = "READ";
    elements.safetyBadge.className = "safety-badge read";
    elements.resultRowCountBadge.textContent = "0 rows";
    elements.executionTimeBadge.textContent = "0.00 ms";
    hideApprovalGate();
    hideLoading();
    elements.errorState.classList.add("hidden");
    elements.resultsTableContainer.classList.add("hidden");
    elements.emptyState.classList.remove("hidden");
    updateStepper("input");
    setSystemState("Ready");
    pendingApprovalState = null;
    elements.queryInput.focus();
  }

  function renderRecentQueries() {
    if (!elements.recentList) return;
    elements.recentList.innerHTML = "";
    recentQueries.forEach(query => {
      const item = document.createElement("button");
      item.className = "recent-item";
      item.textContent = query;
      item.title = query;
      item.addEventListener("click", () => {
        elements.queryInput.value = query;
        runQueryFlow(query);
      });
      elements.recentList.appendChild(item);
    });
  }

  function copySqlToClipboard() {
    const sql = elements.generatedSqlText.textContent;
    if (!sql || sql.startsWith("--")) return;
    navigator.clipboard.writeText(sql).then(() => {
      elements.copyBtnText.textContent = "Copied!";
      setTimeout(() => (elements.copyBtnText.textContent = "Copy"), 1500);
    });
  }

  // --- Settings Handlers ---
  const PROVIDER_METADATA = {
    groq: {
      keyPlaceholder: "gsk_...",
      modelPlaceholder: "llama-3.3-70b-versatile (or llama-3.1-8b-instant)"
    },
    openai: {
      keyPlaceholder: "sk-proj-...",
      modelPlaceholder: "gpt-4o-mini (or gpt-4o, o3-mini)"
    },
    claude: {
      keyPlaceholder: "sk-ant-...",
      modelPlaceholder: "claude-3-5-haiku-20241022 (or claude-3-7-sonnet-20250219)"
    },
    gemini: {
      keyPlaceholder: "AIzaSy...",
      modelPlaceholder: "gemini-2.0-flash (or gemini-1.5-pro)"
    }
  };

  function updateProviderPlaceholders() {
    const prov = elements.settingProvider ? elements.settingProvider.value : "groq";
    const meta = PROVIDER_METADATA[prov] || PROVIDER_METADATA.groq;
    if (elements.settingApiKey) {
      elements.settingApiKey.placeholder = meta.keyPlaceholder;
    }
    if (elements.settingModel) {
      elements.settingModel.placeholder = meta.modelPlaceholder;
    }
  }

  function openSettingsModal() {
    if (elements.settingProvider) {
      elements.settingProvider.value = localStorage.getItem("sqlpilot_user_provider") || "groq";
    }
    updateProviderPlaceholders();
    if (elements.settingApiKey) {
      elements.settingApiKey.value = localStorage.getItem("sqlpilot_user_api_key") || "";
    }
    if (elements.settingModel) {
      elements.settingModel.value = localStorage.getItem("sqlpilot_user_model") || "";
    }
    if (elements.settingsStatusBox) {
      elements.settingsStatusBox.classList.add("hidden");
    }
    if (elements.settingsModal) {
      elements.settingsModal.classList.remove("hidden");
    }
  }

  function closeSettingsModal() {
    if (elements.settingsModal) {
      elements.settingsModal.classList.add("hidden");
    }
  }

  function saveSettings() {
    const key = elements.settingApiKey ? elements.settingApiKey.value.trim() : "";
    const provider = elements.settingProvider ? elements.settingProvider.value : "groq";
    const model = elements.settingModel ? elements.settingModel.value.trim() : "";

    if (key) {
      localStorage.setItem("sqlpilot_user_api_key", key);
      localStorage.setItem("sqlpilot_user_provider", provider);
      localStorage.setItem("sqlpilot_user_model", model);
      if (elements.settingsStatusMsg) {
        elements.settingsStatusMsg.textContent = "Settings saved! Using your personal API key.";
        elements.settingsStatusBox.classList.remove("hidden");
      }
      setTimeout(() => closeSettingsModal(), 1200);
    } else {
      clearSettings();
    }
  }

  function clearSettings() {
    localStorage.removeItem("sqlpilot_user_api_key");
    localStorage.removeItem("sqlpilot_user_provider");
    localStorage.removeItem("sqlpilot_user_model");
    if (elements.settingApiKey) elements.settingApiKey.value = "";
    if (elements.settingModel) elements.settingModel.value = "";
    if (elements.settingsStatusMsg) {
      elements.settingsStatusMsg.textContent = "Custom key cleared. Using server default.";
      elements.settingsStatusBox.classList.remove("hidden");
    }
    setTimeout(() => closeSettingsModal(), 1200);
  }

  // --- Local Agent Connection Handlers ---
  function openUploadModal() {
    if (elements.inputLocalAgentUrl) {
      elements.inputLocalAgentUrl.value = localAgentUrl;
    }
    if (elements.btnUploadSubmit) {
      elements.btnUploadSubmit.disabled = false;
      elements.btnUploadSubmit.textContent = "Connect Local Database";
    }
    if (elements.uploadErrorBox) {
      elements.uploadErrorBox.classList.add("hidden");
    }
    if (elements.uploadModal) {
      elements.uploadModal.classList.remove("hidden");
    }
  }

  function closeUploadModal() {
    if (elements.uploadModal) {
      elements.uploadModal.classList.add("hidden");
    }
  }

  async function handleConnectLocal() {
    const agentUrlInput = elements.inputLocalAgentUrl ? elements.inputLocalAgentUrl.value.trim() : "";
    const dbPathInput = elements.inputLocalDbPath ? elements.inputLocalDbPath.value.trim() : "";

    const agentUrl = (agentUrlInput || "http://127.0.0.1:8765").replace(/\/+$/, "");
    localAgentUrl = agentUrl;
    localStorage.setItem("sqlpilot_local_agent_url", localAgentUrl);

    if (elements.btnUploadSubmit) {
      elements.btnUploadSubmit.disabled = true;
      elements.btnUploadSubmit.textContent = "Connecting to Local Agent...";
    }
    if (elements.uploadErrorBox) {
      elements.uploadErrorBox.classList.add("hidden");
    }

    try {
      if (dbPathInput) {
        // Instruct local agent to connect to specified SQLite file
        const connResp = await fetch(`${agentUrl}/agent/connect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: jsonSafe({ db_path: dbPathInput })
        });
        const connData = await connResp.json();
        if (!connResp.ok || !connData.success) {
          throw new Error(connData.error || `Could not open SQLite database at ${dbPathInput}`);
        }
      }

      const connected = await checkLocalAgent();
      if (!connected) {
        let msg = `Local Agent at ${agentUrl} is unreachable. Please make sure your agent is running.`;
        if (window.location.protocol === "https:" && agentUrl.startsWith("http:")) {
          msg += "\n\nNote: If hosted on HTTPS (Vercel), browsers block HTTP (Mixed Content).\n" +
                 "Options:\n" +
                 "1. Run with SSL: ./run_agent.sh --ssl --db ...\n" +
                 "2. Or in URL bar: Site settings -> allow 'Insecure content'\n" +
                 "3. Or tunnel: npx localtunnel --port 8765";
        }
        throw new Error(msg);
      }

      closeUploadModal();
      resetSession();
      setSystemState("Ready (Local Agent)");
    } catch (err) {
      if (elements.uploadErrorMsg) {
        elements.uploadErrorMsg.textContent = err.message || "Failed to connect to Local Agent.";
        elements.uploadErrorBox.classList.remove("hidden");
      }
    } finally {
      if (elements.btnUploadSubmit) {
        elements.btnUploadSubmit.disabled = false;
        elements.btnUploadSubmit.textContent = "Connect Local Database";
      }
    }
  }

  function attachEventListeners() {
    // Auth Form
    if (elements.authForm) {
      elements.authForm.addEventListener("submit", (e) => {
        e.preventDefault();
        handleLogin(elements.loginUsername.value, elements.loginPassword.value);
      });
    }

    if (elements.btnLogout) {
      elements.btnLogout.addEventListener("click", handleLogout);
    }

    if (elements.btnCredAdmin) {
      elements.btnCredAdmin.addEventListener("click", () => {
        elements.loginUsername.value = "admin";
        elements.loginPassword.value = "admin123";
        handleLogin("admin", "admin123");
      });
    }

    if (elements.btnCredAnalyst) {
      elements.btnCredAnalyst.addEventListener("click", () => {
        elements.loginUsername.value = "analyst";
        elements.loginPassword.value = "analyst123";
        handleLogin("analyst", "analyst123");
      });
    }

    // Settings Modal
    if (elements.settingProvider) {
      elements.settingProvider.addEventListener("change", updateProviderPlaceholders);
    }
    if (elements.btnOpenSettingsModal) {
      elements.btnOpenSettingsModal.addEventListener("click", openSettingsModal);
    }
    if (elements.btnCloseSettingsModal) {
      elements.btnCloseSettingsModal.addEventListener("click", closeSettingsModal);
    }
    if (elements.settingsModal) {
      elements.settingsModal.addEventListener("click", (e) => {
        if (e.target === elements.settingsModal) closeSettingsModal();
      });
    }
    if (elements.btnSaveSettings) {
      elements.btnSaveSettings.addEventListener("click", saveSettings);
    }
    if (elements.btnClearSettings) {
      elements.btnClearSettings.addEventListener("click", clearSettings);
    }

    // Upload DB Modal
    if (elements.btnOpenUploadModal) {
      elements.btnOpenUploadModal.addEventListener("click", openUploadModal);
    }
    if (elements.btnCloseUploadModal) {
      elements.btnCloseUploadModal.addEventListener("click", closeUploadModal);
    }
    if (elements.uploadModal) {
      elements.uploadModal.addEventListener("click", (e) => {
        if (e.target === elements.uploadModal) closeUploadModal();
      });
    }

    // Global Escape Key to close open modals
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeUploadModal();
        closeSettingsModal();
      }
    });
    if (elements.btnUploadSubmit) {
      elements.btnUploadSubmit.addEventListener("click", () => {
        handleConnectLocal();
      });
    }

    if (elements.inputLocalDbPath) {
      elements.inputLocalDbPath.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleConnectLocal();
        }
      });
    }

    if (elements.inputLocalAgentUrl) {
      elements.inputLocalAgentUrl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleConnectLocal();
        }
      });
    }

    // Database Switcher
    if (elements.dbSelect) {
      elements.dbSelect.addEventListener("change", (e) => {
        handleDatabaseSwitch(e.target.value);
      });
    }

    // Query Actions
    elements.btnRunQuery.addEventListener("click", () => runQueryFlow(elements.queryInput.value));
    elements.btnClearPrompt.addEventListener("click", () => {
      elements.queryInput.value = "";
      elements.queryInput.focus();
    });
    if (elements.btnNewQuery) {
      elements.btnNewQuery.addEventListener("click", resetSession);
    }
    elements.btnCopySql.addEventListener("click", copySqlToClipboard);
    elements.btnApproveQuery.addEventListener("click", handleApprove);
    elements.btnRejectQuery.addEventListener("click", handleReject);

    elements.queryInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        runQueryFlow(elements.queryInput.value);
      }
    });

    elements.sampleChips.forEach(chip => {
      chip.addEventListener("click", () => {
        const sampleType = chip.getAttribute("data-sample");
        const question = SAMPLE_QUESTIONS[sampleType];
        if (question) {
          elements.queryInput.value = question;
          runQueryFlow(question);
        }
      });
    });

    elements.schemaSearchInput.addEventListener("input", (e) => {
      renderSchemaTree(loadedTables, e.target.value);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
