window.app = Vue.createApp({
  el: '#vue',
  mixins: [windowMixin],
  data: function () {
    return {
      invoice: null,
      wallet: null,
      currency: null,
      qrCodeDialog: {
        data: {
          payment_request: null
        },
        show: false
      },
      formDialog: {
        data: {
          payment_amount: this.paymentLeft
        },
        show: false
      },
      urlDialog: {
        show: false
      },
      itemsTable: {
        columns: [
          {name: 'item', align: 'left', label: 'Item', field: 'description'},
          {
            name: 'quantity',
            align: 'left',
            label: 'Quantity',
            field: 'quantity'
          },
          {
            name: 'unit_price',
            align: 'left',
            label: 'Unit Price',
            field: 'amount',
            format: val => parseFloat(val / 100).toFixed(2)
          },
          {
            name: 'total_price',
            align: 'right',
            label: 'Total Price',
            format: (_, row) => {
              return parseFloat((row.amount * row.quantity) / 100).toFixed(2)
            }
          }
        ]
      },
      isPrinting: false,
    }
  },
  methods: {
    printInvoice() {
      this.isPrinting = true;
      this.$nextTick(() => {
        window.print();
        this.isPrinting = false;
      }
      )
    },
    openFormDialog() {
      this.formDialog.show = true
      this.formDialog.data.payment_amount = this.paymentLeft
    },
    closeFormDialog() {
      this.formDialog.show = false
    },
    closeQrCodeDialog() {
      this.qrCodeDialog.show = false
    },
    formatedDate(date) {
      return Quasar.date.formatDate(new Date(date), 'YYYY-MM-DD HH:mm')
    },
    async createPayment() {
      const qrCodeDialog = this.qrCodeDialog
      const formDialog = this.formDialog
      const famount = parseInt(formDialog.data.payment_amount * 100)

      try {
        const {data} = await LNbits.api.request(
          'POST',
          `/invoices/api/v1/invoice/${this.invoice.id}/payments`,
          null,
          {famount}
        )
        if (!data.bolt11) {
          throw new Error('No payment request received')
        }

        formDialog.show = false
        formDialog.data = {}

        qrCodeDialog.data = data
        qrCodeDialog.show = true
        this.subscribeToPaylinkWs(data.payment_hash)

        qrCodeDialog.dismissMsg = Quasar.Notify.create({
          timeout: 0,
          message: 'Waiting for payment...'
        })
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    // Payment WS
    subscribeToPaylinkWs(payment_hash) {
      const url = new URL(window.location)
      url.protocol = url.protocol === 'https:' ? 'wss' : 'ws'
      url.pathname = `/api/v1/ws/${payment_hash}`
      const ws = new WebSocket(url)
      console.log(`Subscribing to ${url}`)
      ws.addEventListener('message', async ({data}) => {
        const resp = JSON.parse(data)
        if (!resp.pending || resp.paid) {
          Quasar.Notify.create({
            type: 'positive',
            message: 'Invoice Paid!'
          })
          this.qrCodeDialog.dismissMsg()
          this.qrCodeDialog.show = false
          ws.close()
          setTimeout(() => {
            window.location.reload()
          }, 500)
        }
      })
    }
  },
  computed: {
    amountTotal() {
      return parseFloat(this.invoice_total / 100).toFixed(2)
    },
    paidTotal() {
      return parseFloat(this.payments_total / 100).toFixed(2)
    },
    statusBadgeColor() {
      const colors = {
        draft: 'grey',
        open: 'blue',
        paid: 'green',
        canceled: 'red'
      }
      return colors[this.invoice.status]
    },
    paymentLeft() {
      return (this.invoice_total - this.payments_total) / 100
    }
  },
  created() {
    this.invoice = invoice
    this.invoice_id = invoice.id
    this.wallet = invoice.wallet
    this.currency = invoice.currency
    this.items = invoiceItems
    this.payments = invoicePayments
    this.payments_total = payments_total
    this.invoice_total = invoice_total
    this.shareUrl = shareUrl
  }
})
