# Foris - web administration interface for OpenWrt based on NETCONF
# Copyright (C) 2018-2020 CZ.NIC, z. s. p. o. <https://www.nic.cz>
#
# Foris is distributed under the terms of GNU General Public License v3.
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os

import bottle

from foris.fapi import ForisForm
from foris.form import Checkbox, Textbox, Dropdown
from foris.plugins import ForisPlugin
from foris.config import ConfigPageMixin, add_config_page
from foris.config_handlers import BaseConfigHandler
from foris.utils import messages, reverse
from foris.utils.addresses import prefix_to_mask_4, mask_to_prefix_4
from foris.utils.translators import gettext_dummy as gettext, gettext as _
from foris.state import current_state
from foris.validators import IPv4Prefix, LenRange, RegExp


class OpenvpnConfigHandler(BaseConfigHandler):

    # Translate status obtained via get_status
    CLIENT_STATUS_VALID = gettext("valid")
    CLIENT_STATUS_REVOKED = gettext("revoked")
    CLIENT_STATUS_EXPIRED = gettext("expired")
    CLIENT_STATUS_GENERATING = gettext("generating")
    CLIENT_STATUS_LOST = gettext("lost")

    TRANSLATION_MAP = {
        "valid": CLIENT_STATUS_VALID,
        "revoked": CLIENT_STATUS_REVOKED,
        "expired": CLIENT_STATUS_EXPIRED,
        "generating": CLIENT_STATUS_GENERATING,
        "lost": CLIENT_STATUS_LOST,
    }

    userfriendly_title = gettext("OpenVPN")

    def get_form(self):
        self.backend_data = current_state.backend.perform("openvpn", "get_settings")
        data = {
            "enabled": self.backend_data["enabled"],
            "network": "%s/%d" % (
                self.backend_data["network"], mask_to_prefix_4(self.backend_data["network_netmask"])
            ),
            "default_route": self.backend_data["route_all"],
            "dns": self.backend_data["use_dns"],
            "ipv6": self.backend_data["ipv6"],
            "protocol": self.backend_data["protocol"],
        }

        if self.data:
            # Update from post
            data.update(self.data)

        form = ForisForm("openvpn-configuration", data)
        config_section = form.add_section(name="config", title=_(self.userfriendly_title))
        config_section.add_field(
            Checkbox, name="enabled", label=_("Configuration enabled"),
        )
        config_section.add_field(
            Checkbox, name="ipv6", label=_("Listen on IPv6"),
            hint=_(
                "This option enables openvpn server to listen on IPv6 address. "
                "It could be beneficial for users who does not have a public IPv4 address"
                " and want to use openvpn server."
            ),
        )
        config_section.add_field(
            Dropdown, name="protocol", label=_("Protocol"),
            args=[("udp", "UDP"), ("tcp", "TCP")],
            hint=_(
                "Choose a protocol which will be used when the clients are connecting to the "
                "server. "
            ),
        )
        config_section.add_field(
            Textbox, name="network", label=_("OpenVPN network"),
            validators=[IPv4Prefix()],
            hint=_(
                "This network should be different than any network directly "
                "reachable from the router and the clients."
            ),
        )
        config_section.add_field(
            Checkbox, name="default_route", label=_("All traffic through vpn"),
            hint=_(
                "After enabling this option all traffic from your client "
                "will be routed through the vpn."
            ),
        )
        config_section.add_field(
            Checkbox, name="dns", label=_("Use DNS from vpn"),
            hint=_(
                "After enabling this option your client should start "
                "to use DNS server on your router."
            ),
        )

        def form_callback(data):
            msg = {"enabled": data['enabled']}

            if msg["enabled"]:
                msg["network"], prefix = data['network'].split("/")
                mask = prefix_to_mask_4(int(prefix))
                msg["network_netmask"] = mask
                msg["route_all"] = data['default_route']
                msg["use_dns"] = data['dns']
                msg["ipv6"] = data['ipv6']
                msg["protocol"] = data['protocol']

            res = current_state.backend.perform("openvpn", "update_settings", msg)

            if res["result"]:
                messages.success(
                    _('OpenVPN server configuration was successfully %s.') % (
                        _('enabled') if msg["enabled"] else _('disabled')
                    )
                )
            else:
                messages.error(
                    _('Failed to %s OpenVPN server configuration.') % (
                        _('enable') if msg["enabled"] else _('disable')
                    )
                )

            return "none", None

        form.add_callback(form_callback)
        return form


class OpenvpnConfigPage(ConfigPageMixin, OpenvpnConfigHandler):
    slug = "openvpn"
    menu_order = 60
    template = "openvpn/openvpn"
    template_type = "jinja2"

    def _prepare_render_args(self, arguments, client_form=None, ca=None):
        """ Prepare the arguments for the template.
        :param arguments: target variable
        :type arguments: dict
        """
        arguments['PLUGIN_NAME'] = OpenvpnPlugin.PLUGIN_NAME
        arguments['PLUGIN_STYLES'] = OpenvpnPlugin.PLUGIN_STYLES
        arguments['PLUGIN_STATIC_SCRIPTS'] = OpenvpnPlugin.PLUGIN_STATIC_SCRIPTS
        arguments['PLUGIN_DYNAMIC_SCRIPTS'] = OpenvpnPlugin.PLUGIN_DYNAMIC_SCRIPTS
        status = current_state.backend.perform("openvpn", "get_status")
        arguments['ca_status'] = status["status"]
        client_certs = status["clients"]
        # translate certificat statuses
        for cert in client_certs:
            cert["status_msg"] = OpenvpnConfigHandler.TRANSLATION_MAP.get(
                cert["status"], cert["status"])
        arguments['client_certs'] = client_certs
        arguments['config_form'] = self.form
        arguments['client_form'] = client_form if client_form else self.get_client_form()
        arguments['address_form'] = self.get_address_form(
            {"server-address": self.backend_data["server_hostname"]})

        # prepare current settings to display
        current = {}
        if self.form.data['enabled']:
            current['network'] = "%s/%d" % (
                self.backend_data["network"], mask_to_prefix_4(self.backend_data["network_netmask"])
            )
            current['device'] = self.backend_data["device"]
            current['port'] = self.backend_data["port"]
            current['default_route'] = self.backend_data["route_all"]
            if self.backend_data["routes"]:
                current['route'] = "%s/%d" % (
                    self.backend_data["routes"][0]["network"],
                    mask_to_prefix_4(self.backend_data["routes"][0]["netmask"])
                )
            else:
                current['route'] = "???"

        arguments['current'] = current

    def _action_download_config_or_revoke(self):
        if 'revoke-client' in self.data:
            return self._action_revoke()
        elif 'download-config' in self.data:
            return self._action_download_config()
        raise bottle.HTTPError(404, "Invalid action.")

    def _action_revoke(self):
        """Handle POST requesting revoking client certificate config

        :return: response with token with appropriate HTTP headers
        """
        res = current_state.backend.perform(
            "openvpn", "revoke", {"id": self.data['revoke-client']})
        if res["result"]:
            messages.success(_("The client certificate was successfully revoked."))
        else:
            messages.error(_("Failed to revoke the client certificate."))
        return bottle.redirect(reverse("config_page", page_name="openvpn"))

    def _action_download_config(self):
        """Handle POST requesting download of the openvpn client config

        :return: response with token with appropriate HTTP headers
        """
        form = self.get_address_form(bottle.request.POST)

        res = current_state.backend.perform(
            "openvpn", "get_client_config", {
                "id": self.data['download-config'],
                "hostname": form.data["server-address"] if form.data["server-address"] else "",
            }
        )

        if res["status"] != "valid":
            messages.error(_("Unable to get OpenVPN client config."))
            bottle.redirect(reverse("config_page", page_name="openvpn"))

        bottle.response.set_header("Content-Type", "text/plain")
        # .ovpn is prefered in windows, necessary for iOS and shouldn't make a difference in linux
        bottle.response.set_header("Content-Disposition", 'attachment; filename="turris.ovpn"')
        bottle.response.set_header("Content-Length", len(res["config"]))
        return res["config"]

    def _action_generate_ca(self):
        """Call RPC to generate CA for openvpn server

        :return: redirect to plugin's main page
        """
        current_state.backend.perform("openvpn", "generate_ca")
        messages.success(_("Started to generate CA for the OpenVPN server."))

        return bottle.redirect(reverse("config_page", page_name="openvpn"))

    def _action_generate_client(self):
        """Call RPC to generate a client for openvpn server

        :return: redirect to plugin's main page
        """
        form = self.get_client_form(bottle.request.POST)
        if form.save():
            messages.success(_("Started to generate client certificate for the OpenVPN server."))
            return bottle.redirect(reverse("config_page", page_name="openvpn"))
        else:
            kwargs = {}
            self._prepare_render_args(kwargs, client_form=form)
            return super(OpenvpnConfigPage, self).render(**kwargs)

    def _action_delete_ca(self):
        """Call RPC to delete the CA of the openvpn server

        :return: redirect to plugin's main page
        """
        res = current_state.backend.perform("openvpn", "delete_ca")
        if res["result"]:
            messages.success(_("The OpenVPN CA was successfully deleted."))
        else:
            messages.success(_("Failed to delete the OpenVPN CA."))

        return bottle.redirect(reverse("config_page", page_name="openvpn"))

    def call_action(self, action):
        if bottle.request.method != 'POST':
            # all actions here require POST
            messages.error("Wrong HTTP method.")
            bottle.redirect(reverse("config_page", page_name="openvpn"))
        if action == "download-config":
            return self._action_download_config_or_revoke()
        elif action == "generate-ca":
            return self._action_generate_ca()
        elif action == "generate-client":
            return self._action_generate_client()
        elif action == "delete-ca":
            return self._action_delete_ca()
        raise bottle.HTTPError(404, "Unknown action.")

    def call_ajax_action(self, action):
        if action == "update-clients":
            bottle.response.set_header("Content-Type", "text/html")
            client_certs = current_state.backend.perform("openvpn", "get_status")["clients"]
            for cert in client_certs:
                cert["status_msg"] = OpenvpnConfigHandler.TRANSLATION_MAP.get(
                    cert["status"], cert["status"])
            return bottle.template(
                "openvpn/_clients.html.j2",
                client_certs=client_certs,
                template_adapter=bottle.Jinja2Template,
            )
        if action == "revoke":
            if bottle.request.method != 'POST':
                raise bottle.HTTPError(405, "Method not allowed.")
            try:
                cert_id = bottle.request.POST.get("id")
            except KeyError:
                raise bottle.HTTPError(400, "id is missing.")
            bottle.response.set_header("Content-Type", "application/json")
            return current_state.backend.perform("openvpn", "revoke", {"id": cert_id})

        raise ValueError("Unknown AJAX action.")

    def get_address_form(self, data=None):
        address_form = ForisForm("openvpn", data)
        main_section = address_form.add_section(
            name="address-section", title=None,
        )
        main_section.add_field(
            Textbox, name="server-address", label=_("Router address"), required=False,
            hint=_("A server address which will be present in the client config."),
            default="",
            placeholder=_("use autodetection"),
        )

        return address_form

    def get_client_form(self, data=None):
        client_form = ForisForm("openvpn", data)
        main_section = client_form.add_section(
            name="name", title=None,
        )
        main_section.add_field(
            Textbox, name="client_name", label=_("Client name"), required=True,
            hint=_("The display name for the client. It must be shorter than 64 characters "
                   "and must contain only alphanumeric characters, dots, dashes and "
                   "underscores."),
            validators=[
                RegExp(_("Client name is invalid."), r'[a-zA-Z0-9_.-]+'), LenRange(1, 63)]
        )

        def form_callback(data):
            current_state.backend.perform(
                "openvpn", "generate_client", {"name": self.data['client_name']})
            messages.success(
                _("Started to generate client '%(name)s' for the OpenVPN server.")
                % dict(name=data['client_name'])
            )

            return bottle.redirect(reverse("config_page", page_name="openvpn"))

        client_form.add_callback(form_callback)
        return client_form

    def render(self, **kwargs):
        self._prepare_render_args(kwargs)
        return super(OpenvpnConfigPage, self).render(**kwargs)

    def save(self, *args, **kwargs):
        kwargs['no_messages'] = True  # handle messages in methods of OpenvpnConfigPage
        return super(OpenvpnConfigPage, self).save(*args, **kwargs)


class OpenvpnPlugin(ForisPlugin):
    PLUGIN_NAME = "openvpn"
    DIRNAME = os.path.dirname(os.path.abspath(__file__))
    PLUGIN_STYLES = [
        "css/openvpn.css",
    ]
    PLUGIN_STATIC_SCRIPTS = [
    ]
    PLUGIN_DYNAMIC_SCRIPTS = [
        "openvpn.js"
    ]

    def __init__(self, app):
        super(OpenvpnPlugin, self).__init__(app)
        add_config_page(OpenvpnConfigPage)
