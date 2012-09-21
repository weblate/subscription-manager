#
# Copyright (c) 2010 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.
#
from subscription_manager import managerlib, cert_sorter
from subscription_manager.cert_sorter import CertSorter, FUTURE_SUBSCRIBED, \
    NOT_SUBSCRIBED, EXPIRED, PARTIALLY_SUBSCRIBED
from subscription_manager.branding import get_branding
from subscription_manager.gui import widgets
from subscription_manager.hwprobe import ClassicCheck
from subscription_manager.validity import find_first_invalid_date, \
    ValidProductDateRangeCalculator

import gettext
import gobject
import gtk
import os


_ = gettext.gettext


prefix = os.path.dirname(__file__)
VALID_IMG = os.path.join(prefix, "data/icons/valid.svg")
PARTIAL_IMG = os.path.join(prefix, "data/icons/partial.svg")
INVALID_IMG = os.path.join(prefix, "data/icons/invalid.svg")

ICONSET = {
    'green': gtk.gdk.pixbuf_new_from_file_at_size(VALID_IMG, 13, 13),
    'red': gtk.gdk.pixbuf_new_from_file_at_size(INVALID_IMG, 13, 13),
    'yellow': gtk.gdk.pixbuf_new_from_file_at_size(PARTIAL_IMG, 13, 13)
}


PARTIAL = 0
INVALID = 1
VALID = 2


class InstalledProductsTab(widgets.SubscriptionManagerTab):
    widget_names = widgets.SubscriptionManagerTab.widget_names + \
                ['product_text', 'product_arch_text', 'validity_text',
                 'subscription_text', 'subscription_status_label',
                 'update_certificates_button', 'register_button']

    def __init__(self, backend, consumer, facts, tab_icon,
                 parent, ent_dir, prod_dir):

        super(InstalledProductsTab, self).__init__('installed.glade')

        self.tab_icon = tab_icon

        self.consumer = consumer
        self.product_dir = prod_dir
        self.entitlement_dir = ent_dir

        self.facts = facts
        self.cs = cert_sorter.CertSorter(prod_dir, ent_dir,
                self.facts.get_facts())

        # Product column
        text_renderer = gtk.CellRendererText()
        image_renderer = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn(_('Product'))

        column.set_expand(True)
        column.pack_start(image_renderer, False)
        column.pack_start(text_renderer, False)
        column.add_attribute(image_renderer, 'pixbuf', self.store['image'])
        column.add_attribute(text_renderer, 'text', self.store['product'])
        column.add_attribute(text_renderer, 'cell-background',
                             self.store['background'])
        self.top_view.append_column(column)
        cols = []
        cols.append((column, 'text', 'product'))

        column = self.add_text_column(_('Version'), 'version')
        cols.append((column, 'text', 'version'))

        column = self.add_text_column(_('Status'), 'status')
        cols.append((column, 'text', 'status'))

        column = self.add_date_column(_('Start Date'), 'start_date')
        cols.append((column, 'date', 'start_date'))

        column = self.add_date_column(_('End Date'), 'expiration_date')
        cols.append((column, 'date', 'expiration_date'))

        self.set_sorts(cols)

        self.glade.signal_autoconnect({
            "on_update_certificates_button_clicked":
            parent._update_certificates_button_clicked,
        })
        self.glade.signal_autoconnect({
            "on_register_button_clicked": parent._register_item_clicked,
        })

        self.update_products()

        # Monitor entitlements/products for additions/deletions
        def on_cert_change(filemonitor):
            self.update_products()
            self._set_validity_status()

        backend.monitor_certs(on_cert_change)

    def _calc_subs_providing(self, product_id, compliant_range):
        """
        Calculates the relevant contract IDs and subscription names which are
        providing an installed product during the dates we are covered.
        If an entitlement is outside the date range it is excluded.

        Duplicate contract IDs and subscription names will be filtered.

        Return value is a tuple, a contract IDs set and a subscription names
        set.
        """
        contract_ids = set()
        sub_names = set()

        # No compliant range means we're not fully compliant right now, so
        # not much point displaying the contracts that are covering us:
        if compliant_range is None:
            return contract_ids, sub_names

        for cert in self.entitlement_dir.findAllByProduct(product_id):

            # Only include if this cert overlaps with the overall date range
            # we are currently covered for:
            if compliant_range.has_date(cert.valid_range.begin()) or \
                    compliant_range.has_date(cert.valid_range.end()):

                contract_ids.add(cert.order.contract)
                sub_names.add(cert.order.name)

        return contract_ids, sub_names

    def update_products(self):
        self.store.clear()
        self.cs = cert_sorter.CertSorter(self.product_dir,
                self.entitlement_dir, self.facts.get_facts())
        for product_cert in self.product_dir.list():
            for product in product_cert.products:
                product_id = product.id
                status = self.cs.get_status(product_id)

                entry = {}
                entry['product'] = product.name
                entry['version'] = product.version
                entry['product_id'] = product_id
                entry['arch'] = ",".join(product.architectures)
                # Common properties
                entry['align'] = 0.5

                # TODO:  Pull this date logic out into a separate lib!
                #        This is also used in mysubstab...
                if status != NOT_SUBSCRIBED:

                    range_calculator = ValidProductDateRangeCalculator(self.cs)
                    compliant_range = range_calculator.calculate(product.id)
                    start = ''
                    end = ''
                    if compliant_range:
                        start = compliant_range.begin()
                        end = compliant_range.end()

                    contract_ids, sub_names = self._calc_subs_providing(
                            product_id, compliant_range)
                    name = ", ".join(sub_names)
                    contract = ", ".join(contract_ids)

                    entry['subscription'] = name

                    entry['start_date'] = start
                    entry['expiration_date'] = end

                    if status == FUTURE_SUBSCRIBED:
                        entry['image'] = self._render_icon('red')
                        entry['status'] = _('Future Subscription')
                        entry['validity_note'] = _("Future Subscribed")
                    elif status == EXPIRED:
                        entry['image'] = self._render_icon('red')
                        entry['status'] = _('Expired')
                        sub_numbers = set([])
                        for ent_cert in self.cs.get_entitlements_for_product(product_id):
                            order = ent_cert.order
                            # FIXME:  getSubscription() seems to always be None...?
                            if order.subscription:
                                sub_numbers.add(order.subscription)
                        subs_str = ', '.join(sub_numbers)

                        entry['validity_note'] = \
                             _('Subscription %s is expired') % subs_str
                    elif status == PARTIALLY_SUBSCRIBED:
                        entry['image'] = self._render_icon('yellow')
                        entry['status'] = _('Partially Subscribed')
                        entry['validity_note'] = _("Partially Subscribed")
                    else:
                        entry['image'] = self._render_icon('green')
                        entry['status'] = _('Subscribed')
                        entry['validity_note'] = \
                            _('Covered by contract(s) %s through %s') % \
                            (contract,
                             managerlib.formatDate(entry['expiration_date']))
                else:
                    entry['image'] = self._render_icon('red')
                    entry['status'] = _('Not Subscribed')
                    entry['validity_note'] = _("Not Subscribed")

                self.store.add_map(entry)
        # 811340: Select the first product in My Installed Products
        # table by default.
        selection = self.top_view.get_selection()
        selection.select_path(0)

    def _render_icon(self, icon_id):
        try:
            return ICONSET[icon_id]
        except KeyError:
            print("Iconset does not contain icon for string '%s'" % icon_id)
            raise

    def on_selection(self, selection):
        # Load the entitlement certificate for the selected row:
        product = selection['product']
        self.product_text.get_buffer().set_text(product)

        arch = selection['arch']
        self.product_arch_text.get_buffer().set_text(arch)

        validity = selection['validity_note']
        self.validity_text.get_buffer().set_text(validity)

        subscription = selection['subscription'] or ''
        self.subscription_text.get_buffer().set_text(subscription)

    def on_no_selection(self):
        self.product_text.get_buffer().set_text("")
        self.product_arch_text.get_buffer().set_text("")
        self.validity_text.get_buffer().set_text("")
        self.subscription_text.get_buffer().set_text("")

    def get_type_map(self):
        return {
            'image': gtk.gdk.Pixbuf,
            'product': str,
            'product_id': str,
            'version': str,
            'arch': str,
            'status': str,
            'validity_note': str,
            'subscription': str,
            'start_date': gobject.TYPE_PYOBJECT,
            'expiration_date': gobject.TYPE_PYOBJECT,
            'serial': str,
            'align': float,
            'background': str
        }

    def get_label(self):
        return _('My Installed Products')

    def _set_status_icons(self, status_type):
        img = INVALID_IMG
        if status_type == PARTIAL:
            img = PARTIAL_IMG
        elif status_type == VALID:
            img = VALID_IMG

        pix_buf = gtk.gdk.pixbuf_new_from_file_at_size(img, 13, 13)
        self.tab_icon.set_from_pixbuf(pix_buf)

    def _set_validity_status(self):
        """ Updates the entitlement validity status portion of the UI. """

        if ClassicCheck().is_registered_with_classic():
            self._set_status_icons(VALID)
            self.subscription_status_label.set_text(
                get_branding().RHSMD_REGISTERED_TO_OTHER)
            return

        is_registered = self.consumer.is_valid()
        self.set_registered(is_registered)

        # Look for products which have invalid entitlements
        sorter = CertSorter(self.product_dir, self.entitlement_dir,
                self.facts.get_facts())

        warn_count = len(sorter.expired_products) + \
                len(sorter.unentitled_products)

        partial_count = len(sorter.partially_valid_products)

        if warn_count > 0:
            self._set_status_icons(INVALID)
            # Change wording slightly for just one product
            if warn_count > 1:
                self.subscription_status_label.set_markup(
                        # I18N: Please add newlines if translation is longer:
                        _("%s installed products do not have valid subscriptions.")
                        % warn_count)
            else:
                self.subscription_status_label.set_markup(
                        # I18N: Please add newlines if translation is longer:
                        _("1 installed product does not have a valid subscription."))

        elif partial_count > 0:
            self._set_status_icons(PARTIAL)
            self.subscription_status_label.set_markup(
                # I18N: Please add newlines if translation is longer:
                _("This system does not match subscription limits."))

        else:
            first_invalid = find_first_invalid_date(self.entitlement_dir,
                    self.product_dir, self.facts.get_facts())
            self._set_status_icons(VALID)
            if first_invalid:
                self.subscription_status_label.set_markup(
                        # I18N: Please add newlines if translation is longer:
                        _("System is properly subscribed through %s.") % \
                            managerlib.formatDate(first_invalid))
            else:
                # No product certs installed, no first invalid date, and
                # the subscription assistant can't do anything, so we'll disable
                # the button to launch it:
                self.subscription_status_label.set_text(
                        # I18N: Please add newlines if translation is longer:
                        _("No installed products detected."))

        if not is_registered:
            self.subscription_status_label.set_text(
                # I18N: Please add newlines if translation is longer:
                _("Keep your system up to date by registering."))

    def set_registered(self, is_registered):
        self.update_certificates_button.set_property('visible', is_registered)
        self.register_button.set_property('visible', not is_registered)

    def refresh(self):
        self._set_next_update()
        self._set_validity_status()
