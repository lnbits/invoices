const mapInvoice = obj => {
  obj.time = Quasar.date.formatDate(new Date(obj.time), 'YYYY-MM-DD HH:mm')

  return obj
}

const mapInvoiceItems = obj => {
  obj.amount = parseFloat(obj.amount / 100).toFixed(2)

  return obj
}

window.app = Vue.createApp({
  el: '#vue',
  mixins: [windowMixin],
  data: function () {
    return {
      invoices: [],
      currencyOptions: [],
      loadingInvoice: false,
      invoicesTable: {
        columns: [
          {name: 'id', align: 'left', label: 'ID', field: 'id'},
          {name: 'status', align: 'left', label: 'Status', field: 'status'},
          {name: 'time', align: 'left', label: 'Created', field: 'time'},
          {name: 'wallet', align: 'left', label: 'Wallet', field: 'wallet'},
          {
            name: 'currency',
            align: 'left',
            label: 'Currency',
            field: 'currency'
          },
          {
            name: 'company_name',
            align: 'left',
            label: 'Company Name',
            field: 'company_name'
          },
          {
            name: 'first_name',
            align: 'left',
            label: 'First Name',
            field: 'first_name'
          },
          {
            name: 'last_name',
            align: 'left',
            label: 'Last Name',
            field: 'last_name'
          },
          {name: 'email', align: 'left', label: 'Email', field: 'email'},
          {name: 'phone', align: 'left', label: 'Phone', field: 'phone'},
          {
            name: 'address',
            align: 'left',
            label: 'Address',
            field: 'address'
          }
        ],
        pagination: {
          rowsPerPage: 10
        }
      },
      formDialog: {
        show: false,
        data: {},
        invoiceItems: []
      }
    }
  },
  methods: {
    closeFormDialog() {
      this.formDialog.data = {}
      this.formDialog.invoiceItems = []
    },
    walletKey(wallet_id) {
      const key = _.findWhere(this.g.user.wallets, {id: wallet_id})?.adminkey
      if (!key) {
        Quasar.Notify.create({
          type: 'warning',
          message: 'The selected invoice wallet is unavailable.'
        })
      }
      return key
    },
    async showEditModal(invoice) {
      if (this.loadingInvoice) return

      const key = this.walletKey(invoice.wallet)
      if (!key) return

      this.loadingInvoice = true
      try {
        const {data} = await LNbits.api.request(
          'GET',
          `/invoices/api/v1/invoice/${invoice.id}`,
          key
        )
        this.formDialog.invoiceItems = data.items.map(mapInvoiceItems)
        this.formDialog.data = invoice
        this.formDialog.show = true
      } catch (error) {
        if (error.response) {
          LNbits.utils.notifyApiError(error)
        } else {
          Quasar.Notify.create({
            type: 'warning',
            message: 'Could not load invoice items.'
          })
        }
      } finally {
        this.loadingInvoice = false
      }
    },
    getInvoices() {
      LNbits.api
        .request(
          'GET',
          '/invoices/api/v1/invoices?all_wallets=true',
          this.g.user.wallets[0].adminkey
        )
        .then(response => {
          this.invoices = response.data.map(mapInvoice)
        })
    },
    resetFormDialog() {
      this.formDialog.data = {}
      this.formDialog.invoiceItems = []
      this.formDialog.show = false
    },
    saveInvoice() {
      const data = this.formDialog.data
      const walletKey = this.walletKey(data.wallet)
      if (!walletKey) return
      data.items = this.formDialog.invoiceItems

      if (data.id) {
        return this.updateInvoice(data, walletKey)
      }

      LNbits.api
        .request('POST', '/invoices/api/v1/invoice', walletKey, data)
        .then(response => {
          this.invoices.push(mapInvoice(response.data))

          this.resetFormDialog()
        })
        .catch(LNbits.utils.notifyApiError)
    },
    updateInvoice(data, walletKey) {
      LNbits.api
        .request('PUT', `/invoices/api/v1/invoice/${data.id}`, walletKey, data)
        .then(response => {
          this.invoices = this.invoices.filter(
            invoice => invoice.id !== data.id
          )
          this.invoices.push(mapInvoice(response.data))

          this.resetFormDialog()
        })
        .catch(LNbits.utils.notifyApiError)
    },
    deleteInvoice(invoice_id, wallet_id) {
      const adminkey = this.walletKey(wallet_id)
      if (!adminkey) return
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this Invoice?')
        .onOk(() => {
          LNbits.api
            .request(
              'DELETE',
              `/invoices/api/v1/invoice/${invoice_id}`,
              adminkey
            )
            .then(response => {
              if (response.status == 200) {
                this.invoices = _.reject(
                  this.invoices,
                  obj => obj.id === invoice_id
                )
              }
            })
            .catch(LNbits.utils.notifyApiError)
        })
    },
    exportCSV() {
      LNbits.utils.exportCSV(this.invoicesTable.columns, this.invoices)
    }
  },
  async created() {
    if (this.g.user.wallets.length) {
      this.getInvoices()
      this.currencyOptions = await LNbits.api.getCurrencies()
    }
  }
})
