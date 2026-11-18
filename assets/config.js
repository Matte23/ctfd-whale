// ctfd-whale's tabs in CTFd's Config page (declared in config.json).
// CTFd's own config page script saves the forms; this adds the behavior
// specific to these tabs. Registered as an admin script: it is loaded on
// every admin page, so it does nothing unless the tabs are present.
(function () {
    const forms = document.querySelectorAll("form.whale-settings");
    if (!forms.length) {
        return;
    }
    const $ = CTFd.lib.$;
    const TAB_KEY = "ctfd-whale-settings-tab";

    // show only the fields of the selected router (all are saved anyway)
    const routerType = document.getElementById("router-type");
    if (routerType) {
        const showRouter = function () {
            document.querySelectorAll("[data-whale-router]").forEach(function (el) {
                el.hidden = el.dataset.whaleRouter !== routerType.value;
            });
        };
        showRouter();
        routerType.addEventListener("change", showRouter);
    }

    // the SSL fields only matter while "Use SSL" is checked
    const sslOption = document.getElementById("docker-use-ssl");
    const sslFields = document.getElementById("docker-ssl-config");
    if (sslOption && sslFields) {
        const showSsl = function () {
            sslFields.hidden = !sslOption.checked;
        };
        showSsl();
        sslOption.addEventListener("change", showSsl);
    }

    // CTFd reloads the page after saving: come back to the saved tab
    forms.forEach(function (form) {
        form.addEventListener("submit", function () {
            const pane = form.closest(".tab-pane");
            if (pane && pane.id) {
                sessionStorage.setItem(TAB_KEY, pane.id);
            }
        });
    });
    const savedTab = sessionStorage.getItem(TAB_KEY);
    if (savedTab) {
        sessionStorage.removeItem(TAB_KEY);
        $('a[href="#' + savedTab + '"]').tab("show");
    }

    // docker and router connectivity, shown at the top of their tabs
    CTFd.fetch("/api/v1/plugins/ctfd-whale/admin/checks", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
    })
        .then(function (response) {
            return response.json();
        })
        .then(function (response) {
            if (!response.success) {
                return;
            }
            document.querySelectorAll("[data-whale-check]").forEach(function (el) {
                const error = response.data[el.dataset.whaleCheck];
                el.className = "whale-check alert " + (error ? "alert-danger" : "alert-success");
                el.textContent = error || "Connection OK";
            });
        });
})();
