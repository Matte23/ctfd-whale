const $ = CTFd.lib.$;
const ADMIN_API = "/api/v1/plugins/ctfd-whale/admin/container";

function htmlentities(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function writeClipboard(str) {
    // navigator.clipboard only exists on HTTPS (or localhost) pages
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(str);
    }
    const el = document.createElement("textarea");
    el.value = str;
    el.setAttribute("readonly", "");
    el.style.position = "absolute";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    document.body.removeChild(el);
    return Promise.resolve();
}

function copyToClipboard(event, str) {
    const target = $(event.currentTarget);
    writeClipboard(String(str)).then(function () {
        target.tooltip({ title: "Copied!", trigger: "manual" });
        target.tooltip("show");
        setTimeout(function () {
            target.tooltip("hide");
        }, 1500);
    });
}

$(".click-copy").click(function (e) {
    copyToClipboard(e, $(this).data("copy"));
});

async function containerAction(method, containerId) {
    const response = await CTFd.fetch(ADMIN_API + "?container_id=" + encodeURIComponent(containerId), {
        method: method,
        credentials: "same-origin",
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
        },
        body: "{}",
    });
    try {
        return await response.json();
    } catch (e) {
        return { success: false, message: "HTTP " + response.status };
    }
}

// Runs the action on every container, then reloads; failures are reported
// first, with the server's message for each container.
async function runOnContainers(method, containerIds) {
    const results = await Promise.all(
        containerIds.map(async function (id) {
            return { id: id, result: await containerAction(method, id) };
        })
    );
    const failed = results.filter(function (r) {
        return !r.result.success;
    });
    if (failed.length === 0) {
        location.reload();
        return;
    }
    CTFd.ui.ezq.ezAlert({
        title: "Some actions failed",
        body: failed
            .map(function (r) {
                return "Container #" + htmlentities(r.id) + ": " + htmlentities(r.result.message);
            })
            .join("<br>"),
        button: "OK",
        success: function () {
            location.reload();
        },
    });
}

function selectedContainers() {
    return $("input[data-container-id]:checked")
        .map(function () {
            return $(this).data("container-id");
        })
        .toArray();
}

function confirmBulk(title, verb, method) {
    const containers = selectedContainers();
    CTFd.ui.ezq.ezQuery({
        title: title,
        body: `Are you sure you want to ${verb} the selected ${containers.length} container(s)?`,
        success: function () {
            return runOnContainers(method, containers);
        },
    });
}

function confirmOne(title, verb, method, containerId) {
    CTFd.ui.ezq.ezQuery({
        title: title,
        body: `<span>Are you sure you want to ${verb} <strong>Container #${htmlentities(containerId)}</strong>?</span>`,
        success: function () {
            return runOnContainers(method, [containerId]);
        },
    });
}

$("#containers-renew-button").click(function () {
    confirmBulk("Renew Containers", "renew", "PATCH");
});

$("#containers-delete-button").click(function () {
    confirmBulk("Delete Containers", "delete", "DELETE");
});

$(".delete-container").click(function (e) {
    e.preventDefault();
    confirmOne("Destroy Container", "delete", "DELETE", $(this).attr("container-id"));
});

$(".renew-container").click(function (e) {
    e.preventDefault();
    confirmOne("Renew Container", "renew", "PATCH", $(this).attr("container-id"));
});
