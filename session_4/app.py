#!/usr/bin/env python3

from typing import Final

from beaker import *
from pyteal import *


class AuctionState:
    highest_bidder: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.bytes,
        default=Bytes(""),
        descr="Address of the highest bidder",
    )

    auction_end: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Timestamp of the end of the auction",
    )

    highest_bid: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Amount of the highest bid (uALGO)",
    )

    asa_amt: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="Total amount of ASA being auctioned",
    )

    asa: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="ID of the ASA being auctioned",
    )

    payment_asa: Final[GlobalStateValue] = GlobalStateValue(
        stack_type=TealType.uint64,
        default=Int(0),
        descr="ID of the ASA being used for payment",
    )


app = Application("Auction", state=AuctionState)


@app.create(bare=True)
def create() -> Expr:
    # Set all global state to the default values
    return app.initialize_global_state()

# Only allow app creator to opt the app account into a ASA
@app.external(authorize=Authorize.only(Global.creator_address()))
def opt_into_asset(asset: abi.Asset, payment_asset: abi.Asset) -> Expr:
    """ opt into assets """
    return Seq(
        # Verify a ASA hasn't already been opted into
        Assert(app.state.asa == Int(0)),
        # Verify a ASA hasn't already been opted into
        Assert(app.state.payment_asa == Int(0)),
        # Save ASA ID in global state
        app.state.asa.set(asset.asset_id()),
        # Save ASA ID in global state
        app.state.payment_asa.set(payment_asset.asset_id()),
        
        # Submit opt-in transaction: 0 asset transfer to self
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.fee: Int(0),  # cover fee with outer txn
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.xfer_asset: asset.asset_id(),
                TxnField.asset_amount: Int(0),
            },
        ),
        InnerTxnBuilder.Next(),  # This indicates we're moving to constructing the next txn in the group
        InnerTxnBuilder.SetFields(
{
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.fee: Int(0),  # cover fee with outer txn
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.xfer_asset: payment_asset.asset_id(),
                TxnField.asset_amount: Int(0),
            }    
        ),
        InnerTxnBuilder.Submit(),
    )


@app.external(authorize=Authorize.only(Global.creator_address()))
def start_auction(
    starting_price: abi.Uint64,
    length: abi.Uint64,
    axfer: abi.AssetTransferTransaction,
) -> Expr:
    """ start auction """
    return Seq(
        # Ensure the auction hasn't already been started
        Assert(app.state.auction_end.get() == Int(0)),
        # Verify axfer
        Assert(axfer.get().asset_receiver() == Global.current_application_address()),
        Assert(axfer.get().xfer_asset() == app.state.asa),
        # Set global state
        app.state.asa_amt.set(axfer.get().asset_amount()),
        app.state.auction_end.set(Global.latest_timestamp() + length.get()),
        app.state.highest_bid.set(starting_price.get()), # what happens if no one bids
    )

# pay
# - pay receiver amount in asset
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
def assert_auction_not_over() -> Expr:
    """ auction not over """
    return Assert(Global.latest_timestamp() < app.state.auction_end.get())

@Subroutine(TealType.none)
def assert_auction_over() -> Expr:
    """ auction over """
    return not assert_auction_not_over()

@app.external
def bid(payment: abi.AssetTransferTransaction, previous_bidder: abi.Account) -> Expr:
    """ accept new bid """
    return Seq(
        # Ensure auction hasn't ended
        #assert_auction_not_over(),
        # Verify payment transaction
        #Assert(payment.get().asset_amount() > app.state.highest_bid.get()), # amount is gt highest bid
        #Assert(payment.get().asset_sender() == Txn.sender()), # txn sender is payment sender
        #Assert(payment.get().asset_receiver() == Global.current_application_address()), # is to app address
        #Assert(payment.get().xfer_asset() == app.state.payment_asa.get()), # is in payment token
        # Return previous bid if there was one
        # TODO add fallback for optout attack
        If(
            app.state.highest_bidder.get() != Bytes(""), # not sure if this works are if it is translated into the zero address
            pay(app.state.highest_bidder.get(), app.state.highest_bid.get(), app.state.payment_asa.get()),
        ),
        # Set global state
        app.state.highest_bid.set(payment.get().asset_amount()), # set new highest bid
        app.state.highest_bidder.set(payment.get().sender()), # set new highest bidder
    )


@app.external
def claim_bid() -> Expr:
    """ send payment asas to creator """
    return Seq(
        # Auction end check is commented out for automated testing
        #assert_auction_over(),
        # Asset previous highest bidder not ""
        pay(Global.creator_address(), app.state.highest_bid.get(), app.state.payment_asa.get())
    )


@app.external
def claim_asset(asset: abi.Asset, asset_creator: abi.Account) -> Expr:
    """ send asa to highest bidder  """
    return Seq(
        # Auction end check is commented out for automated testing
        #assert_auction_over(),
        # Send ASA to highest bidder
        pay(app.state.highest_bidder.get(), app.state.highest_bid.get(), app.state.asa.get())
    )


@app.delete
def delete() -> Expr:
    """ delete app """
    return Seq(
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.Payment,
                TxnField.fee: Int(0),  
                TxnField.receiver: Global.creator_address(),
                TxnField.close_remainder_to: Global.creator_address(),
                TxnField.amount: Int(0),
            }
        ),
        InnerTxnBuilder.Next(),  
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.fee: Int(0), 
                TxnField.xfer_asset: app.state.asa.get(), ### !!!
                TxnField.asset_amount: Int(0),
                TxnField.asset_receiver: Global.creator_address(),
                TxnField.asset_close_to: Global.creator_address(),
            }
        ),
        InnerTxnBuilder.Next(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.fee: Int(0), 
                TxnField.xfer_asset: app.state.payment_asa.get(), ### !!!
                TxnField.asset_amount: Int(0),
                TxnField.asset_receiver: Global.creator_address(),
                TxnField.asset_close_to: Global.creator_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
    )
    InnerTxnBuilder.Execute(
        {
            TxnField.type_enum: TxnType.Payment,
            TxnField.fee: Int(0),  # cover fee with outer txn
            TxnField.receiver: Global.creator_address(),
            # close_remainder_to to sends full balance, including 0.1 account MBR
            TxnField.close_remainder_to: Global.creator_address(),
            # we are closing the account, so amount can be zero
            TxnField.amount: Int(0),
        }
    )


if __name__ == "__main__":
    app.build().export()
