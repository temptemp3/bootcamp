#!/usr/bin/env python3

from typing import Final

from beaker import *
from pyteal import *

import pyteal as pt


class RollupState:
    manager: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Global.creator_address(),
        descr="Manager"
    )
    url: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=pt.Bytes(""),
        descr="Url"
    )
    reserve: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Global.creator_address(),
        descr="Reserve"
    )
    note: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=pt.Bytes(""),
        descr="Note"
    )
    token_id: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Token Id"
    )


app = Application("Rollup", state=RollupState)


@Subroutine(TealType.none)
def pay(receiver: Expr, amount: Expr, asset: Expr) -> Expr:
    """ pay asa """
    return InnerTxnBuilder.SetFields(
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
            TxnField.receiver: app.state.manager.get(),
            # close_remainder_to to sends full balance, including 0.1 account MBR
            TxnField.close_remainder_to: app.state.manager.get(),
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


@app.external(authorize=Authorize.only(app.state.manager.get()))
def mint(url: abi.String, reserve: abi.Account, note: abi.String, asset: abi.Asset) -> Expr:
    """ mint smart nft """
    return Seq(
        ##########################################
        # assertions
        ##########################################
        Assert(app.state.url.get() == Bytes("")),
        Assert(app.state.note.get() == Bytes("")),
        Assert(app.state.reserve.get() == Global.creator_address()),
        Assert(app.state.token_id.get() == Int(0)),
        ##########################################
        # inner txns
        ##########################################
        InnerTxnBuilder.Begin(),
        opt_in(asset.asset_id()),
        InnerTxnBuilder.Submit(), 
        ##########################################
        # state update
        ##########################################
        app.state.url.set(url.encode()),
        app.state.note.set(note.encode()),
        app.state.reserve.set(reserve.address()),
        app.state.token_id.set(asset.asset_id()),
        ##########################################
    )

# fees:
# - requires fee 0.002A

@app.external
def opt_in_asset(asset: abi.Asset) -> Expr:
    """ opt in assets """
    return Seq(
        ##########################################
        # inner txns
        ##########################################
        InnerTxnBuilder.Begin(),
        opt_in(asset.asset_id()),
        InnerTxnBuilder.Submit(),
        ##########################################
    )

# fees:
# - requires fee 0.002A


@app.external
def opt_out_asset(asset: abi.Asset, asset_receiver: abi.Account) -> Expr:
    """ opt in assets """
    return Seq(
        ##########################################
        # assertions
        ##########################################
        Assert(app.state.token_id.get() != asset.asset_id()),
        ##########################################
        # inner txns
        ##########################################
        InnerTxnBuilder.Begin(),
        opt_out(asset.asset_id(), asset_receiver.address()),
        InnerTxnBuilder.Submit(),
        ##########################################
    )

# fees:
# - requires fee 0.002A

@app.external(authorize=Authorize.only(app.state.manager.get()))
def withdraw(asset: abi.Asset, asset_amount: abi.Uint64, asset_receiver: abi.Account) -> Expr:
    """ opt in assets """
    return Seq(
        ##########################################
        # assertions
        ##########################################
        #Assert(app.state.token_id.get() != asset.asset_id()),
        ##########################################
        # inner txns
        ##########################################
        InnerTxnBuilder.Begin(),
        pay(asset_receiver.address(), asset_amount.get(), asset.asset_id()),
        InnerTxnBuilder.Submit(),
        ##########################################
    )


# fees:
# - requires fee 0.002A

@app.external
def grant(manager: abi.Account, axfer: abi.AssetTransferTransaction) -> Expr:
    """ update manager """
    return Seq(
        ##########################################
        # assertions
        ##########################################
        Assert(axfer.get().asset_receiver() ==
            Global.current_application_address()),
        Assert(axfer.get().xfer_asset() == app.state.token_id.get()),
        Assert(axfer.get().asset_amount() > Int(0)),
        ##########################################
        # inner txns
        ##########################################
        InnerTxnBuilder.Begin(),
        pay(manager.address(), axfer.get().asset_amount(), axfer.get().xfer_asset()),
        InnerTxnBuilder.Submit(), 
        ##########################################
        # state update
        ##########################################
        app.state.manager.set(manager.address())
        ##########################################
    )

# fees:
# - requires fee 0.002A
# on complete:
# - requires DeleteApplicationOC

@app.delete(authorize=Authorize.only(app.state.manager.get()))
def delete() -> Expr:
    return Seq(
        ###############################################
        # inner txns
        ###############################################
        InnerTxnBuilder.Begin(),
        free_app_mbr(),
        InnerTxnBuilder.Submit()
        ###############################################
    )


if __name__ == "__main__":
    app.build().export()
