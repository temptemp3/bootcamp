#!/usr/bin/env python3

from typing import Final

from beaker import *
from pyteal import *


class SaleState:
    sale_start: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Timestamp of the start of the sale",
    )

    sale_price: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Amount of the price (ASA-AU)",
    )

    asa_amt: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total amount of ASA being sold",
    )

    asa: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="ID of the ASA being sold",
    )

    payment_asa: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="ID of the ASA being used for payment",
    )


app = Application("Sale", state=SaleState)


@Subroutine(TealType.none)
def pay(receiver: Expr, amount: Expr, asset: Expr) -> Expr:
    """ pay asa """
    return InnerTxnBuilder.Execute(
        {
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.asset_receiver: receiver,
            TxnField.asset_amount: amount,
            TxnField.xfer_asset: asset,
            TxnField.fee: Int(0),  # cover fee with outer txn
        }
    )


@Subroutine(TealType.none)
def pay_with_close_remainder_to(receiver: Expr, amount: Expr, asset: Expr, close_remainder_to: Expr) -> Expr:
    """ pay asa with close remainder to """
    return InnerTxnBuilder.SetFields(
        {
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.asset_receiver: receiver,
            TxnField.asset_amount: amount,
            TxnField.xfer_asset: asset,
            TxnField.fee: Int(0),
            TxnField.asset_close_to: close_remainder_to
        }
    )


@Subroutine(TealType.none)
def free_app_mbr() -> Expr:
    """ free application minimum balance requirement """
    return InnerTxnBuilder.SetFields(
        {  # send MBR to creator_address
            TxnField.type_enum: TxnType.Payment,
            TxnField.fee: Int(0),  # cover fee with outer txn
            TxnField.receiver: Global.creator_address(),
            # close_remainder_to to sends full balance, including 0.1 account MBR
            TxnField.close_remainder_to: Global.creator_address(),
            # we are closing the account, so amount can be zero
            TxnField.amount: Int(0),
        }
    )


@Subroutine(TealType.none)
def opt_in(asset_id: Expr) -> Expr:
    """ optin single asset """
    return InnerTxnBuilder.SetFields(
        {
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.fee: Int(0),  # cover fee with outer txn
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.xfer_asset: asset_id,
            TxnField.asset_amount: Int(0),
        },
    )


@Subroutine(TealType.none)
def opt_out(asset_id: Expr, close_remainder_to: Expr) -> Expr:
    """ optin single asset """
    return InnerTxnBuilder.SetFields(
        {
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.fee: Int(0),  # cover fee with outer txn
            TxnField.xfer_asset: asset_id,
            TxnField.asset_amount: Int(0),
            TxnField.asset_receiver: Global.creator_address(),
            TxnField.asset_close_to: close_remainder_to
        },
    )


@app.create(bare=True)
def create() -> Expr:
    # Set all global state to the default values
    return app.initialize_global_state()

# Send 0.3A prior to transaction to satisfy MBR
# Requires fee 0.003A
# Only allow app creator to opt the app account into a ASA


@app.external(authorize=Authorize.only(Global.creator_address()))
def opt_into_asset(asset: abi.Asset, payment_asset: abi.Asset) -> Expr:
    """ opt into assets """
    return Seq(
        ##########################################
        # assertions
        # 1. app state sale_start eq 0
        # 1. app state asa eq 0
        # 1. app state payment_asa eq 0
        ##########################################
        Assert(app.state.sale_start.get() == Int(0)),
        Assert(app.state.asa == Int(0)),
        Assert(app.state.payment_asa == Int(0)),
        ##########################################
        # state update
        # 1. asa
        # 1. payment_asas
        ##########################################
        app.state.asa.set(asset.asset_id()),
        app.state.payment_asa.set(payment_asset.asset_id()),
        ##########################################
        # inner txns
        ##########################################
        InnerTxnBuilder.Begin(),
        opt_in(asset.asset_id()),
        InnerTxnBuilder.Next(),
        opt_in(payment_asset.asset_id()),
        InnerTxnBuilder.Submit(),
        ##########################################
    )


@app.external(authorize=Authorize.only(Global.creator_address()))
def start_sale(
    price: abi.Uint64,
    axfer: abi.AssetTransferTransaction,
) -> Expr:
    """ start sale """
    return Seq(
        ##########################################
        # assertions
        # 1. app state sale_start eq 0
        # 1. app state sale_price eq 0
        # 1. app state asa_amt eq 0
        # 1. axfer to application address
        # 1. axfer asset is asa
        # 1. price gt 0
        ##########################################
        Assert(app.state.asa != Int(0)),
        Assert(app.state.payment_asa != Int(0)),
        Assert(app.state.sale_start.get() == Int(0)),
        Assert(app.state.sale_price.get() == Int(0)),
        Assert(app.state.asa_amt.get() == Int(0)),
        Assert(axfer.get().asset_receiver() ==
               Global.current_application_address()),
        Assert(axfer.get().xfer_asset() == app.state.asa),
        Assert(price.get() > Int(0)),
        ##########################################
        # state update
        # 1. sale_start
        # 1. sale_price
        # 1. asa_amt
        ##########################################
        app.state.sale_start.set(Global.latest_timestamp()),
        app.state.sale_price.set(price.get()),
        app.state.asa_amt.set(axfer.get().asset_amount()),
        ##########################################
        # inner txns
        ##########################################
    )

##################################################
# fees:
# - requires fee 0.003A
##################################################


@app.external
def claim_asset(asset_amount: abi.Uint64, asset: abi.Asset, payment_asset: abi.Asset, app_creator: abi.Account, asset_creator: abi.Account, payment_asset_creator: abi.Account) -> Expr:
    """ send asa back to initiator of sale in case of no purchase """
    return Seq(
        ##############################################
        # assertions
        # 1. app state sale_start ne 0
        # 1. app state asa_amt ne 0
        # 1. app state sale_start ne 0
        # 1. app state sale_price ne 0
        # 1. app state asa is asset asset_id
        # 1. app state payment_asa is payment_asset asset_id
        # 1. app_creator address is global creator_address
        ##############################################
        Assert(app.state.sale_start.get() != Int(0)),
        Assert(app.state.asa_amt.get() != Int(0)),
        Assert(app.state.sale_start.get() != Int(0)),
        Assert(app.state.sale_price.get() != Int(0)),
        Assert(app.state.asa_amt.get() == asset_amount.get()),
        Assert(app.state.asa == asset.asset_id()),
        Assert(app.state.payment_asa == payment_asset.asset_id()),
        Assert(app_creator.address() == Global.creator_address()),
        ###############################################
        # state update (initialize)
        ###############################################
        app.initialize_global_state(),
        ###############################################
        # inner txns
        ###############################################
        InnerTxnBuilder.Begin(),
        pay_with_close_remainder_to(
            app_creator.address(),
            asset_amount.get(),
            asset.asset_id(),
            asset_creator.address()
        ),
        InnerTxnBuilder.Next(),
        opt_out(
            payment_asset.asset_id(),
            payment_asset_creator.address()  # [!] not checked
        ),
        InnerTxnBuilder.Next(),
        free_app_mbr(),
        InnerTxnBuilder.Submit()
        ##############################################
    )
##################################################

# fees:
# - requires fee 0.002A
# on complete:
# - requires DeleteApplicationOC


@app.delete
def delete() -> Expr:
    return Seq(
        ###############################################
        # inner txns
        ###############################################
        InnerTxnBuilder.Begin(),
        free_app_mbr(),
        InnerTxnBuilder.Submit()
    )

# fees:
# - requires fee 0.004A
# on complete:


@app.external
def buy(payment: abi.AssetTransferTransaction, asset_amount: abi.Uint64, asset: abi.Asset, payment_asset: abi.Asset, app_creator: abi.Account, asset_creator: abi.Account, payment_asset_creator: abi.Account) -> Expr:
    """ accept purchase """
    return Seq(
        ###############################################
        # assertions
        ###############################################
        Assert(app_creator.address() == Global.creator_address()),
        Assert(app.state.asa == asset.asset_id()),
        Assert(app.state.asa_amt == asset_amount.get()),
        Assert(app.state.payment_asa == payment_asset.asset_id()),
        Assert(app.state.payment_asa == payment.get().xfer_asset()),
        Assert(app.state.sale_price.get() <= payment.get().asset_amount()),
        Assert(payment.get().asset_receiver() == app_creator.address()),
        ###############################################
        # state update (initialize)
        ###############################################
        app.initialize_global_state(),
        ###############################################
        # inner txns
        ###############################################
        InnerTxnBuilder.Begin(),
        pay_with_close_remainder_to(
            payment.get().sender(),
            asset_amount.get(),
            asset.asset_id(),
            asset_creator.address()  # [!] not checked
        ),
        InnerTxnBuilder.Next(),
        opt_out(
            payment_asset.asset_id(),
            payment_asset_creator.address()  # [!] not checked
        ),
        InnerTxnBuilder.Next(),
        free_app_mbr(),
        InnerTxnBuilder.Submit()
        ###############################################
    )


if __name__ == "__main__":
    app.build().export()
