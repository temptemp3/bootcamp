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

# Send 0.3A prior to transaction to satisfy MBR
# Requires fee 0.003A
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
        # This indicates we're moving to constructing the next txn in the group
        InnerTxnBuilder.Next(),
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
        Assert(axfer.get().asset_receiver() ==
              Global.current_application_address()),
        #
        Assert(axfer.get().xfer_asset() == app.state.asa),
        # Set global state
        app.state.asa_amt.set(axfer.get().asset_amount()),
        app.state.auction_end.set(Global.latest_timestamp() + length.get()),
        app.state.highest_bid.set(starting_price.get()),
    )

##################################################
# claim_asset_no_bid
# accounts:
# - app_creator
# - asset_creator
# - payment_asset_creator
# assets:
# - asset
# - payment_asset
# assertions:
# - state auction is over 
# - state auction has no bid
# - param app creator is valid
# - param asset is valid
# - param payment asset is valid
# payload:
# - send asset back to app creator and opt out of
#   payment asset
# fees:
# - requires fee 0.003A
##################################################
@app.external
def claim_asset_no_bid(asset: abi.Asset, payment_asset: abi.Asset, app_creator: abi.Account, asset_creator: abi.Account, payment_asset_creator: abi.Account) -> Expr:
    """ send asa back to initiator of auction in case of no bid """
    return Seq(
        ##############################################
        # Assertions
        #  State auction is over
        #  State auction has no bid
        #  Param app creator is valid
        #  Param asset is valid
        #  Param payment asset is valid
        ##############################################
        # Assertions
        # State auction is over
        Assert(Global.latest_timestamp() >=
               app.state.auction_end.get()),  # auction over
        # State auction has no bid
        Assert(app.state.highest_bidder.get() == Bytes("")),  # has no bid
        # Param app creator is valid
        Assert(app_creator.address() == Global.creator_address()),
        # Param asset is valid
        Assert(app.state.asa == asset.asset_id()), # asset valid
        # Param payment asset is valid
        Assert(app.state.payment_asa == payment_asset.asset_id()), # payment asset valid
        ##############################################
        # send asset back to app creator and opt out of
        # payment asset
        ##############################################
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.fee: Int(0),  # cover fee with outer txn
                TxnField.xfer_asset: app.state.asa,
                TxnField.asset_amount: app.state.asa_amt,
                TxnField.asset_receiver: app_creator.address(),
                # close to asset creator since they are guranteed to be opted in
                TxnField.asset_close_to: asset_creator.address()
            }
        ),
        InnerTxnBuilder.Next(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.fee: Int(0),  # cover fee with outer txn
                TxnField.xfer_asset: app.state.payment_asa, ###
                TxnField.asset_amount: Int(0),
                TxnField.asset_receiver: app_creator.address(),
                # close to asset creator since they are guranteed to be opted in
                TxnField.asset_close_to: payment_asset_creator.address() ###
            },
        ),
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
    return InnerTxnBuilder.Execute(
        {
            TxnField.type_enum: TxnType.Payment,
            TxnField.fee: Int(0),  # cover fee with outer txn
            TxnField.receiver: Global.creator_address(),
            # close_remainder_to to sends full balance, including 0.1 account MBR
            TxnField.close_remainder_to: Global.creator_address(),
            # we are closing the account, so amount can be zero
            TxnField.amount: Int(0),
        },
    )

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


@app.external
def bid(payment: abi.AssetTransferTransaction, asset: abi.Asset, previous_bidder: abi.Account) -> Expr:
    """ accept new bid """
    return Seq(
        # Ensure auction hasn't ended
        Assert(Global.latest_timestamp() < app.state.auction_end.get()),
        # Verify payment transaction
        # amount is gt highest bid
        Assert(payment.get().asset_amount() > app.state.highest_bid.get()),
        # txn sender is payment sender
        # TODO restore assertion belowz
        #Assert(payment.get().asset_sender() == Txn.sender()),
        ##
        Assert(payment.get().asset_receiver() ==
               Global.current_application_address()),  # is to app address
        Assert(payment.get().xfer_asset() ==
               app.state.payment_asa.get()),  # is in payment token
        # Return previous bid if there was one
        # TODO add fallback for optout attack
        If(
            # not sure if this works are if it is translated into the zero address
            app.state.highest_bidder.get() != Bytes(""),
            pay(app.state.highest_bidder.get(),
                app.state.highest_bid.get(), app.state.payment_asa.get()),
        ),
        ##########################################
        #  Set global state
        #   Set new highest bid
        #   Set new highest bidder
        ##########################################
        # Update state
        #  Set global state
        #   Set new highest bid
        app.state.highest_bid.set(
            payment.get().asset_amount()),
        #   Set new highest bidder
        app.state.highest_bidder.set(
            payment.get().sender()),
        ##########################################
    )


@app.external
def claim_bid(payment_asset: abi.Asset, creator_address: abi.Account) -> Expr:
    """ send payment asas to creator """
    return Seq(
        # Auction end check is commented out for automated testing
        Assert(Global.latest_timestamp() >=
               app.state.auction_end.get()),  # auction over
        # Auction has bid
        Assert(app.state.highest_bidder.get() != Bytes("")),  # has bid
        # Asset previous highest bidder not ""
        InnerTxnBuilder.Execute(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.fee: Int(0),  # cover fee with outer txn
                TxnField.xfer_asset: app.state.payment_asa,
                TxnField.asset_amount: app.state.highest_bid,
                TxnField.asset_receiver: Global.creator_address(),
                # close to creator address since it is guaranteed to be opted in to recdeive
                TxnField.asset_close_to: Global.creator_address(),
            }
        ),
    )


@ app.external
def claim_asset(asset: abi.Asset, highest_bidder: abi.Account, asset_creator: abi.Account) -> Expr:
    """ send asa to highest bidder  """
    return Seq(
        # Auction end check is commented out for automated testing
        Assert(Global.latest_timestamp() >=
               app.state.auction_end.get()),  # auction over
        # Auction has bid
        Assert(app.state.highest_bidder.get() != Bytes("")),  # has bid
        # Send ASA to highest bidder
        InnerTxnBuilder.Execute(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.fee: Int(0),  # cover fee with outer txn
                TxnField.xfer_asset: app.state.asa,
                TxnField.asset_amount: app.state.asa_amt,
                TxnField.asset_receiver: app.state.highest_bidder,
                # close to asset creator since they are guranteed to be opted in
                TxnField.asset_close_to: asset_creator.address()
            }
        )
    )

if __name__ == "__main__":
    app.build().export()
