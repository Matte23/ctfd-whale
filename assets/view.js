CTFd._internal.challenge.data = undefined;

// TODO: Remove in CTFd v4.0 (as in CTFd's standard challenge)
CTFd._internal.challenge.renderer = null;

CTFd._internal.challenge.preRender = function () {};

// TODO: Remove in CTFd v4.0 (as in CTFd's standard challenge)
CTFd._internal.challenge.render = null;

(function () {
    const $ = CTFd.lib.$;
    // when an expired instance is still there (auto-clean hasn't run yet)
    const RECHECK_MS = 5000;
    let countdown = null;

    function escapeHtml(value) {
        return String(value === undefined || value === null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // The server sends access info as plain text (a URL or a command, maybe
    // on several lines): escape it, then turn lines that are URLs into links.
    function renderAccess(text) {
        return String(text || "")
            .split("\n")
            .map(function (line) {
                const escaped = escapeHtml(line);
                if (/^https?:\/\/\S+$/.test(line)) {
                    return '<a target="_blank" rel="noopener noreferrer" href="' + escaped + '">' + escaped + "</a>";
                }
                return escaped;
            })
            .join("<br>");
    }

    function request(method) {
        const url = "/api/v1/plugins/ctfd-whale/container?challenge_id=" + CTFd._internal.challenge.data.id;
        return CTFd.fetch(url, {
            method: method,
            credentials: "same-origin",
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
            },
            // a JSON body: CTFd treats the request as an API call
            body: method === "GET" ? undefined : "{}",
        }).then(function (response) {
            return response.json();
        });
    }

    function alert(title, message) {
        CTFd._functions.events.eventAlert({
            title: title,
            html: escapeHtml(message),
            button: "OK",
        });
    }

    function stopCountdown() {
        if (countdown !== null) {
            clearInterval(countdown);
            countdown = null;
        }
    }

    function showPanel(started) {
        $("#whale-panel-started").toggleClass("d-none", !started);
        $("#whale-panel-stopped").toggleClass("d-none", started);
    }

    function showInstance(data) {
        $("#whale-challenge-user-access").html(renderAccess(data.user_access));
        $("#whale-challenge-lan-domain").text(data.lan_domain);
        // count down from a fixed expiry, so the display doesn't drift
        const expiresAt = Date.now() + data.remaining_time * 1000;
        function tick() {
            const seconds = Math.max(0, Math.round((expiresAt - Date.now()) / 1000));
            $("#whale-challenge-count-down").text(seconds);
            if (seconds === 0) {
                stopCountdown();
                setTimeout(loadInfo, RECHECK_MS);
            }
        }
        tick();
        if (data.remaining_time > 0) {
            countdown = setInterval(tick, 1000);
        }
        showPanel(true);
    }

    function loadInfo() {
        stopCountdown();
        return request("GET").then(function (response) {
            if (!response.success) {
                alert("Fail", response.message);
                return;
            }
            if (response.data.remaining_time !== undefined) {
                showInstance(response.data);
            } else {
                showPanel(false);
            }
        });
    }

    function action(method, buttonId) {
        const button = $(buttonId);
        const label = button.text();
        button.text("Waiting...").prop("disabled", true);
        return request(method)
            .then(function (response) {
                if (response.success) {
                    loadInfo();
                    alert("Success", response.message);
                } else {
                    alert("Fail", response.message);
                }
            })
            .finally(function () {
                button.text(label).prop("disabled", false);
            });
    }

    CTFd._internal.challenge.boot = function () {
        return action("POST", "#whale-button-boot");
    };
    CTFd._internal.challenge.destroy = function () {
        return action("DELETE", "#whale-button-destroy");
    };
    CTFd._internal.challenge.renew = function () {
        return action("PATCH", "#whale-button-renew");
    };

    CTFd._internal.challenge.postRender = function () {
        // The core theme inserts the challenge view (Alpine) after postRender
        // runs, so the buttons don't exist yet: delegate from the document.
        // The script is loaded again for every challenge opened: replace the
        // previous handlers instead of stacking them.
        $(document)
            .off(".whale")
            .on("click.whale", "#whale-button-boot", CTFd._internal.challenge.boot)
            .on("click.whale", "#whale-button-destroy", CTFd._internal.challenge.destroy)
            .on("click.whale", "#whale-button-renew", CTFd._internal.challenge.renew);
        loadInfo();
    };
})();

CTFd._internal.challenge.submit = function (preview) {
    const body = {
        challenge_id: CTFd._internal.challenge.data.id,
        submission: CTFd.lib.$("#challenge-input").val(),
    };
    const params = {};
    if (preview) {
        params["preview"] = true;
    }
    return CTFd.api.post_challenge_attempt(params, body);
};
