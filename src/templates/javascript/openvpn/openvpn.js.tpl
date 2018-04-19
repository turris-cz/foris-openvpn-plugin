var renew_clients = function() {
  $.get('{{ url("config_ajax", page_name="openvpn") }}', {action: "update-clients"})
    .done(function(response, status, xhr) {
      if (xhr.status == 200) {
        // Redraw
        $("#openvpn-clients").replaceWith(response);
        Foris.overrideOpenvpnRevoke();
      } else {
        // Logout or other
        window.location.reload();
      }
    })
    .fail(function(xhr) {
        if (xhr.responseJSON && xhr.responseJSON.loggedOut && xhr.responseJSON.loginUrl) {
            window.location.replace(xhr.responseJSON.loginUrl);
            return;
        }
    });
};

Foris.WS["openvpn"] = function (data) {
  switch (data.action) {
    case "generate_client":
      if (data.data.status == "failed") {
      }
    case "revoke":
      renew_clients();
      return;
    case "generate_ca":
      // reload current window
      window.location.reload();
      return;
  };
};

Foris.overrideOpenvpnRevoke = function() {
  $('#openvpn-clients button[name="revoke-client"]').click(function (event) {
    event.preventDefault();
    var id = $(this).val();
    $(this).text('{{ trans("Revoking...") }}');
    $(this).prop('disabled', true);
    var data = $(this).parents("form:first").serialize();
    data += "&action=revoke&id=" + id;
    $.ajax({
      type: "POST",
      url: '{{ url("config_ajax", page_name="openvpn") }}',
      data: data,
      success: function(data, text, xhr) {
        // No need to perform rerender will be handled via ws
      },
    });
  });
}

$(document).ready(function() {
  $('#delete-ca-form').on('click', function(e) {
    var answer = confirm("{{ trans("Are you sure you want to delete the OpenVPN CA?") }}");
    if (!answer) {
      e.preventDefault();
    }
  });
  $('#field-enabled_1').click(function () {
    if ($(this).prop('checked')) {
      $('#openvpn-config-form div:not(:first):not(:last)').show();
      $('.openvpn-config-current').show();
    } else {
      $('#openvpn-config-form div:not(:first):not(:last)').hide();
      $('.openvpn-config-current').hide();
    }
  });
  if ($('#field-enabled_1').is(':checked')) {
      $('#openvpn-config-form div:not(:first):not(:last)').show();
  } else {
      $('#openvpn-config-form div:not(:first):not(:last)').hide();
  };
  $(".hint-text").hide();
  Foris.overrideOpenvpnRevoke();
});
