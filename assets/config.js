const $ = CTFd.lib.$;

async function saveSettings(params) {
    const response = await CTFd.api.patch_config_list({}, params);
    if (response && response.success) {
        location.reload();
        return;
    }
    CTFd.ui.ezq.ezAlert({
        title: "Error",
        body: "The settings could not be saved.",
        button: "OK",
    });
}

$(".config-section > form").submit(function (event) {
    event.preventDefault();
    // CTFd's serializeJSON sends checkboxes as true/false
    saveSettings($(this).serializeJSON());
});

$("#router-type").change(function () {
    saveSettings({ "whale:router_type": $(this).val() });
});

// the SSL fields only matter while "Use SSL" is checked
(function () {
    const option = document.getElementById("docker-use-ssl");
    const fields = document.getElementById("docker-ssl-config");
    if (!option || !fields) {
        return;
    }
    const sync = function () {
        fields.hidden = !option.checked;
    };
    sync();
    option.addEventListener("change", sync);
})();
